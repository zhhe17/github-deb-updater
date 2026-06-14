"""下载与安装服务"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx

from app.config import config
from app.models import UpdateResult


def _get_proxy_url() -> Optional[str]:
    """获取代理 URL，优先使用 HTTPS_PROXY/HTTP_PROXY，避免 ALL_PROXY 中的 SOCKS 协议"""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if proxy and proxy.startswith("http"):
        return proxy
    return None


async def download_deb(
    url: str,
    package_name: str,
    version: str,
    progress_callback=None,
) -> Optional[Path]:
    """下载 deb 包

    Args:
        url: 下载链接
        package_name: 软件包名称
        version: 版本号
        progress_callback: 进度回调函数 (downloaded, total)

    Returns:
        Path: 下载的文件路径，失败返回 None
    """
    cache_dir = config.cache_path
    target_path = cache_dir / f"{package_name}_{version}.deb"

    # 检查缓存是否存在且完整
    if target_path.exists():
        if _verify_deb(target_path):
            return target_path
        else:
            target_path.unlink()

    # 下载文件
    try:
        async with httpx.AsyncClient(
            timeout=300.0, follow_redirects=True, proxy=_get_proxy_url()
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return None

                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(target_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total > 0:
                            progress = int(downloaded * 100 / total)
                            await progress_callback(downloaded, total, progress)

    except (httpx.NetworkError, httpx.TimeoutException, IOError):
        if target_path.exists():
            target_path.unlink()
        return None

    # 验证下载的文件
    if not _verify_deb(target_path):
        target_path.unlink()
        return None

    return target_path


def _verify_deb(path: Path) -> bool:
    """验证 deb 包完整性"""
    try:
        result = subprocess.run(
            ["dpkg-deb", "--info", str(path)],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


async def install_deb(
    deb_path: Path,
    pre_install_cmd: str = "",
    post_install_cmd: str = "",
) -> UpdateResult:
    """安装 deb 包

    Returns:
        UpdateResult: 安装结果
    """
    package_name = deb_path.stem.split("_")[0]

    # 执行前置命令
    if pre_install_cmd:
        try:
            result = subprocess.run(
                pre_install_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return UpdateResult(
                    success=False,
                    message=f"前置命令执行失败: {result.stderr}",
                    package_name=package_name,
                )
        except subprocess.TimeoutExpired:
            return UpdateResult(
                success=False,
                message="前置命令执行超时",
                package_name=package_name,
            )

    # 安装 deb 包
    try:
        result = subprocess.run(
            ["sudo", "dpkg", "-i", str(deb_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            # 尝试修复依赖
            fix_result = subprocess.run(
                ["sudo", "apt-get", "install", "-f", "-y"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if fix_result.returncode != 0:
                return UpdateResult(
                    success=False,
                    message=f"安装失败: {result.stderr}",
                    package_name=package_name,
                )

    except subprocess.TimeoutExpired:
        return UpdateResult(
            success=False,
            message="安装超时",
            package_name=package_name,
        )

    # 执行后置命令
    if post_install_cmd:
        try:
            subprocess.run(
                post_install_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            pass  # 后置命令超时不影响安装结果

    return UpdateResult(
        success=True,
        message="安装成功",
        package_name=package_name,
    )


def cleanup_cache(max_age_days: int = 7):
    """清理旧缓存文件

    Args:
        max_age_days: 最大保留天数
    """
    cache_dir = config.cache_path
    if not cache_dir.exists():
        return

    import time
    current_time = time.time()
    max_age_seconds = max_age_days * 24 * 3600

    for deb_file in cache_dir.glob("*.deb"):
        file_age = current_time - deb_file.stat().st_mtime
        if file_age > max_age_seconds:
            deb_file.unlink()
