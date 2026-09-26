"""把 GitHub 资产或官网直链解析为可比较、可安装的 deb 候选包。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from app.config import config
from app.models import CandidatePackage, ReleaseInfo
from app.services.installer import (
    download_deb,
    get_system_architecture,
    inspect_deb,
)
from app.services.metadata_cache import (
    asset_key,
    read_metadata,
    web_asset_key,
    write_metadata,
)
from app.services.version import VersionError, validate_version
from app.services.web_source import read_deb_control_head


class CandidateError(RuntimeError):
    pass


def release_cache_key(pkg, release: ReleaseInfo) -> str:
    """构建元数据缓存身份；GitHub 源沿用旧键，保证既有缓存继续有效。"""
    if (release.source or "github") == "github":
        return asset_key(
            pkg.repo,
            release.asset_id,
            release.asset_size,
            release.asset_updated_at or "",
            release.download_url,
        )
    path = release.identity_path or urlsplit(release.download_url).path
    return web_asset_key(
        path or release.download_url,
        release.etag or "",
        release.asset_updated_at or "",
        release.asset_size or 0,
    )


def _usable_metadata(
    metadata: dict | None, expected_package: str, system_architecture: str
) -> bool:
    if not metadata:
        return False
    if metadata["package"] != expected_package:
        return False
    if metadata["architecture"] not in (system_architecture, "all"):
        return False
    try:
        validate_version(metadata["version"])
    except VersionError:
        return False
    return True


def _has_stable_identity(release: ReleaseInfo) -> bool:
    """ETag/Last-Modified/大小全空时，缓存键退化为纯路径哈希：
    同一路径发布新版会让元数据缓存永久命中旧版本，此时必须绕过缓存。
    GitHub 源的键基于 asset_id，本身就是稳定身份，不受此影响。"""
    if (release.source or "github") == "github":
        return True
    return bool(release.etag or release.asset_updated_at or release.asset_size)


async def get_candidate_package(
    pkg, release: ReleaseInfo, progress_callback=None, *, require_file: bool = True
) -> CandidatePackage:
    key = release_cache_key(pkg, release)
    stable_identity = _has_stable_identity(release)
    if not stable_identity:
        # 无身份头的来源不做任何缓存：每次都拿一次性的键，走部分读/全量
        # 下载取得 deb 内部的真实版本，绝不复用旧结果。
        key = f"nocache-{uuid.uuid4().hex[:12]}"
    system_architecture = await asyncio.to_thread(get_system_architecture)
    if not system_architecture:
        raise CandidateError("无法读取当前系统架构")
    if not require_file:
        metadata = None
        if stable_identity:
            metadata = await asyncio.to_thread(read_metadata, config.cache_path, key)
        if _usable_metadata(metadata, pkg.name, system_architecture):
            return CandidatePackage(
                path="",
                package_name=metadata["package"],
                deb_version=metadata["version"],
                architecture=metadata["architecture"],
                release=release,
            )
        # 缓存未命中：Range 部分读只取 control 段即可拿到版本，
        # 服务器不支持 Range 或压缩格式无法解析时回退全量下载。
        head_metadata = await asyncio.to_thread(
            read_deb_control_head, release.download_url
        )
        if head_metadata and _usable_metadata(
            head_metadata, pkg.name, system_architecture
        ):
            if stable_identity:
                await asyncio.to_thread(
                    write_metadata, config.cache_path, key, head_metadata
                )
            return CandidatePackage(
                path="",
                package_name=head_metadata["package"],
                deb_version=head_metadata["version"],
                architecture=head_metadata["architecture"],
                release=release,
            )
        if head_metadata:
            # 部分读结果与配置不一致：CDN 可能对同一资产返回了新旧不同的
            # 构建（上游重传后边缘缓存不一致），不轻信，回退全量下载复核。
            print(
                f"[candidates] 部分读取的 deb ({head_metadata['package']} "
                f"{head_metadata['version']}) 与配置不符，回退全量下载复核"
            )
    path = await download_deb(
        release.download_url,
        pkg.name,
        key,
        progress_callback,
    )
    if not path:
        raise CandidateError("deb 下载或完整性校验失败")
    if release.asset_size and Path(path).stat().st_size != release.asset_size:
        Path(path).unlink(missing_ok=True)
        raise CandidateError(f"deb 文件大小不符（期望 {release.asset_size} 字节）")
    metadata = await asyncio.to_thread(inspect_deb, Path(path))
    if not metadata:
        raise CandidateError("无法读取 deb 内部元数据")
    _validate_head_metadata(metadata, pkg, system_architecture)
    if stable_identity:
        await asyncio.to_thread(write_metadata, config.cache_path, key, metadata)
    return CandidatePackage(
        path=str(path),
        package_name=metadata["package"],
        deb_version=metadata["version"],
        architecture=metadata["architecture"],
        release=release,
    )


def _validate_head_metadata(
    metadata: dict, pkg, system_architecture: str
) -> None:
    """校验 deb 元数据与配置一致；不一致是显式错误而不是"换个候选"。"""
    if metadata["package"] != pkg.name:
        raise CandidateError(
            f"deb 内部包名为 {metadata['package']}，与配置 {pkg.name} 不一致"
        )
    if metadata["architecture"] not in (system_architecture, "all"):
        raise CandidateError(
            f"deb 架构为 {metadata['architecture']}，当前系统为 {system_architecture}"
        )
    try:
        validate_version(metadata["version"])
    except VersionError as error:
        raise CandidateError(str(error)) from error
