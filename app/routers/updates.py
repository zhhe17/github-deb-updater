"""更新操作路由"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates

from app.config import config
from app.models import UpdateResult
from app.services.candidates import CandidateError, get_candidate_package
from app.services.github import github_service
from app.services.installer import install_deb
from app.services.version import VersionError, get_installed_version, is_update_needed

router = APIRouter(prefix="/updates", tags=["updates"])
templates = Jinja2Templates(directory="app/templates")


async def _upgrade_one(pkg) -> UpdateResult:
    """执行单个软件包升级"""
    local_version = await asyncio.to_thread(get_installed_version, pkg.name)
    release = await github_service.get_release_info(pkg.repo, pkg.asset_pattern)
    if not release:
        return UpdateResult(
            success=False,
            message=f"未找到匹配 {pkg.asset_pattern} 的正式 Release 资产",
            package_name=pkg.name,
            old_version=local_version,
        )
    try:
        candidate = await get_candidate_package(pkg, release)
    except CandidateError as error:
        return UpdateResult(
            success=False,
            message=str(error),
            package_name=pkg.name,
            old_version=local_version,
        )

    if not is_update_needed(local_version, candidate.deb_version):
        return UpdateResult(
            success=True,
            message="已是最新版本",
            package_name=pkg.name,
            old_version=local_version,
            new_version=candidate.deb_version,
        )

    result = await install_deb(
        Path(candidate.path),
        pkg.pre_install,
        pkg.post_install,
        expected_package=pkg.name,
        expected_version=candidate.deb_version,
    )
    result.old_version = local_version
    result.new_version = result.new_version or candidate.deb_version
    return result


@router.post("/api/upgrade/{name}")
async def api_upgrade_package(name: str):
    """更新单个软件包 API（同步等待完成，适合脚本调用）"""
    pkg = config.get_package(name)
    if not pkg:
        raise HTTPException(status_code=404, detail=f"软件包 {name} 不存在")

    try:
        result = await _upgrade_one(pkg)
    except VersionError as error:
        return UpdateResult(success=False, message=str(error), package_name=pkg.name)
    # 统一返回 200 + success 字段，方便前端处理（避免 HTTPException 吞掉 message）
    return result


@router.post("/api/upgrade-all")
async def api_upgrade_all():
    """批量更新所有软件包 API"""
    results = []
    for pkg in config.packages:
        try:
            result = await _upgrade_one(pkg)
            results.append(result)
        except Exception as e:
            results.append(
                UpdateResult(
                    success=False,
                    message=str(e),
                    package_name=pkg.name,
                )
            )
    return results


@router.websocket("/ws/upgrade/{name}")
async def websocket_upgrade(websocket: WebSocket, name: str):
    """WebSocket 升级进度推送（前端主路径）"""
    await websocket.accept()

    pkg = config.get_package(name)
    if not pkg:
        await websocket.send_json({"status": "error", "message": "软件包不存在"})
        await websocket.close()
        return

    try:
        await websocket.send_json(
            {
                "status": "checking",
                "message": "正在获取版本信息...",
            }
        )

        local_version = await asyncio.to_thread(get_installed_version, pkg.name)
        release = await github_service.get_release_info(pkg.repo, pkg.asset_pattern)
        if not release:
            await websocket.send_json(
                {
                    "status": "error",
                    "message": f"未找到匹配模式的正式 Release 资产: {pkg.asset_pattern}",
                }
            )
            await websocket.close()
            return

        async def progress_callback(downloaded, total, progress):
            try:
                await websocket.send_json(
                    {
                        "status": "downloading",
                        "message": f"正在读取 {release.tag_name} 的 deb 版本... ({progress}%)",
                        "progress": progress,
                    }
                )
            except Exception:
                pass

        try:
            candidate = await get_candidate_package(pkg, release, progress_callback)
        except CandidateError as error:
            await websocket.send_json({"status": "error", "message": str(error)})
            await websocket.close()
            return

        if not is_update_needed(local_version, candidate.deb_version):
            await websocket.send_json(
                {
                    "status": "completed",
                    "message": f"已是最新版本 ({candidate.deb_version})",
                }
            )
            await websocket.close()
            return

        await websocket.send_json(
            {
                "status": "downloading",
                "message": f"已验证候选 deb {candidate.deb_version}（Release {release.tag_name}）",
                "progress": 100,
            }
        )

        await websocket.send_json(
            {
                "status": "installing",
                "message": "正在安装（dpkg，可能需要 sudo 权限）...",
                "progress": 100,
            }
        )

        result = await install_deb(
            Path(candidate.path),
            pkg.pre_install,
            pkg.post_install,
            expected_package=pkg.name,
            expected_version=candidate.deb_version,
        )

        if result.success:
            await websocket.send_json(
                {
                    "status": "completed",
                    "message": f"更新成功: {local_version or '未安装'} → {candidate.deb_version}",
                }
            )
        else:
            await websocket.send_json(
                {
                    "status": "error",
                    "message": f"安装失败: {result.message}",
                }
            )

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await websocket.send_json({"status": "error", "message": str(e)})
        except Exception:
            pass

    try:
        await websocket.close()
    except Exception:
        pass
