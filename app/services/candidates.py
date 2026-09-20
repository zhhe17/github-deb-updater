"""把 GitHub 资产解析为可比较、可安装的 deb 候选包。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import config
from app.models import CandidatePackage, ReleaseInfo
from app.services.installer import (
    download_deb,
    get_system_architecture,
    inspect_deb,
)
from app.services.metadata_cache import asset_key, read_metadata, write_metadata
from app.services.version import VersionError, validate_version


class CandidateError(RuntimeError):
    pass


async def get_candidate_package(
    pkg, release: ReleaseInfo, progress_callback=None, *, require_file: bool = True
) -> CandidatePackage:
    key = asset_key(
        pkg.repo,
        release.asset_id,
        release.asset_size,
        release.asset_updated_at or "",
        release.download_url,
    )
    system_architecture = await asyncio.to_thread(get_system_architecture)
    if not system_architecture:
        raise CandidateError("无法读取当前系统架构")
    if not require_file:
        metadata = await asyncio.to_thread(read_metadata, config.cache_path, key)
        if (
            metadata
            and metadata["package"] == pkg.name
            and metadata["architecture"] in (system_architecture, "all")
        ):
            try:
                await asyncio.to_thread(validate_version, metadata["version"])
            except VersionError:
                pass  # 无效缓存重新从 deb 读取。
            else:
                return CandidatePackage(
                    path="",
                    package_name=metadata["package"],
                    deb_version=metadata["version"],
                    architecture=metadata["architecture"],
                    release=release,
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
    if metadata["package"] != pkg.name:
        raise CandidateError(
            f"deb 内部包名为 {metadata['package']}，与配置 {pkg.name} 不一致"
        )
    if metadata["architecture"] not in (system_architecture, "all"):
        raise CandidateError(
            f"deb 架构为 {metadata['architecture']}，当前系统为 {system_architecture}"
        )
    await asyncio.to_thread(validate_version, metadata["version"])
    await asyncio.to_thread(write_metadata, config.cache_path, key, metadata)
    return CandidatePackage(
        path=str(path),
        package_name=metadata["package"],
        deb_version=metadata["version"],
        architecture=metadata["architecture"],
        release=release,
    )
