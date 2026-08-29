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
        progress_callback: 进度回调函数 (downloaded, total, progress)

    Returns:
        Path: 下载的文件路径，失败返回 None
    """
    cache_dir = config.cache_path
    # 版本号里可能有 + 等字符，做简单清洗
    safe_version = version.replace("/", "_")
    target_path = cache_dir / f"{package_name}_{safe_version}.deb"

    if target_path.exists():
        if await asyncio.to_thread(_verify_deb, target_path):
            if progress_callback:
                await progress_callback(1, 1, 100)
            return target_path
        target_path.unlink(missing_ok=True)

    tmp_path = target_path.with_suffix(".deb.partial")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
            proxy=_get_proxy_url(),
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    print(f"[download] HTTP {response.status_code}: {url}")
                    return None

                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_reported = -1

                with open(tmp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total > 0:
                            progress = int(downloaded * 100 / total)
                            # 降低推送频率，避免刷爆 WebSocket
                            if progress != last_reported and (
                                progress == 100 or progress - last_reported >= 2
                            ):
                                last_reported = progress
                                await progress_callback(downloaded, total, progress)

        tmp_path.replace(target_path)

    except (httpx.NetworkError, httpx.TimeoutException, IOError) as e:
        print(f"[download] 失败: {type(e).__name__}: {e}")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        return None

    if not await asyncio.to_thread(_verify_deb, target_path):
        target_path.unlink(missing_ok=True)
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


def _run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_cmd(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def install_deb(
    deb_path: Path,
    pre_install_cmd: str = "",
    post_install_cmd: str = "",
) -> UpdateResult:
    """安装 deb 包（子进程放到线程池，避免阻塞事件循环）"""
    package_name = deb_path.stem.split("_")[0]

    if pre_install_cmd:
        try:
            result = await asyncio.to_thread(_run_shell, pre_install_cmd, 60)
            if result.returncode != 0:
                return UpdateResult(
                    success=False,
                    message=f"前置命令执行失败: {result.stderr or result.stdout}",
                    package_name=package_name,
                )
        except subprocess.TimeoutExpired:
            return UpdateResult(
                success=False,
                message="前置命令执行超时",
                package_name=package_name,
            )

    try:
        # 优先直接 dpkg；若当前进程已是 root，不需要 sudo
        if os.geteuid() == 0:
            install_args = ["dpkg", "-i", str(deb_path)]
            fix_args = ["apt-get", "install", "-f", "-y"]
        else:
            install_args = ["sudo", "-n", "dpkg", "-i", str(deb_path)]
            fix_args = ["sudo", "-n", "apt-get", "install", "-f", "-y"]

        result = await asyncio.to_thread(_run_cmd, install_args, 180)

        if result.returncode != 0:
            # 可能是依赖问题，尝试修复
            fix_result = await asyncio.to_thread(_run_cmd, fix_args, 180)
            if fix_result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                if "password" in err.lower() or "a password is required" in err.lower():
                    err = (
                        "需要 root 权限安装 deb。"
                        "请用 root 启动 Web 服务，或配置免密 sudo。"
                        f" 原始错误: {err}"
                    )
                return UpdateResult(
                    success=False,
                    message=f"安装失败: {err or '未知错误'}",
                    package_name=package_name,
                )

            # 修复依赖后再装一次
            result = await asyncio.to_thread(_run_cmd, install_args, 180)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                return UpdateResult(
                    success=False,
                    message=f"安装失败: {err or '未知错误'}",
                    package_name=package_name,
                )

    except subprocess.TimeoutExpired:
        return UpdateResult(
            success=False,
            message="安装超时",
            package_name=package_name,
        )
    except FileNotFoundError as e:
        return UpdateResult(
            success=False,
            message=f"命令不存在: {e}",
            package_name=package_name,
        )

    if post_install_cmd:
        try:
            await asyncio.to_thread(_run_shell, post_install_cmd, 60)
        except subprocess.TimeoutExpired:
            pass

    return UpdateResult(
        success=True,
        message="安装成功",
        package_name=package_name,
    )


async def uninstall_package(package_name: str) -> UpdateResult:
    """卸载已安装的软件包，但保留其配置文件和管理条目。"""
    try:
        # 不使用 autoremove，避免自动移除用户仍可能需要的依赖。
        if os.geteuid() == 0:
            uninstall_args = ["apt-get", "remove", "-y", package_name]
        else:
            uninstall_args = ["sudo", "-n", "apt-get", "remove", "-y", package_name]

        result = await asyncio.to_thread(_run_cmd, uninstall_args, 180)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            if "password" in err.lower() or "a password is required" in err.lower():
                err = (
                    "需要 root 权限卸载软件包。"
                    "请用 root 启动 Web 服务，或配置免密 sudo。"
                    f" 原始错误: {err}"
                )
            return UpdateResult(
                success=False,
                message=f"卸载失败: {err or '未知错误'}",
                package_name=package_name,
            )
    except subprocess.TimeoutExpired:
        return UpdateResult(
            success=False,
            message="卸载超时",
            package_name=package_name,
        )
    except FileNotFoundError as e:
        return UpdateResult(
            success=False,
            message=f"命令不存在: {e}",
            package_name=package_name,
        )

    return UpdateResult(
        success=True,
        message="卸载成功（已保留配置文件和软件包管理条目）",
        package_name=package_name,
    )


def cleanup_cache(max_age_days: int = 7):
    """清理旧缓存文件"""
    cache_dir = config.cache_path
    if not cache_dir.exists():
        return

    import time

    current_time = time.time()
    max_age_seconds = max_age_days * 24 * 3600

    for deb_file in cache_dir.glob("*.deb"):
        try:
            file_age = current_time - deb_file.stat().st_mtime
            if file_age > max_age_seconds:
                deb_file.unlink()
        except OSError:
            pass
