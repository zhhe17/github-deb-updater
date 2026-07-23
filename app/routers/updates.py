"""更新操作路由"""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates

from app.config import config
from app.models import UpdateResult
from app.services.github import github_service
from app.services.version import get_installed_version, is_update_needed
from app.services.installer import download_deb, install_deb

router = APIRouter(prefix="/updates", tags=["updates"])
templates = Jinja2Templates(directory="app/templates")


async def _upgrade_one(pkg) -> UpdateResult:
    """执行单个软件包升级"""
    local_version = await asyncio.to_thread(get_installed_version, pkg.name)
    latest_version, download_url = await github_service.get_version_and_url(
        pkg.repo, pkg.asset_pattern
    )

    if not latest_version:
        return UpdateResult(
            success=False,
            message="无法获取最新版本",
            package_name=pkg.name,
            old_version=local_version,
        )

    if not download_url:
        return UpdateResult(
            success=False,
            message=f"未找到匹配 {pkg.asset_pattern} 的 deb 资产",
            package_name=pkg.name,
            old_version=local_version,
            new_version=latest_version,
        )

    if not is_update_needed(local_version, latest_version):
        return UpdateResult(
            success=True,
            message="已是最新版本",
            package_name=pkg.name,
            old_version=local_version,
            new_version=latest_version,
        )

    deb_path = await download_deb(download_url, pkg.name, latest_version)
    if not deb_path:
        return UpdateResult(
            success=False,
            message="下载失败",
            package_name=pkg.name,
            old_version=local_version,
            new_version=latest_version,
        )

    result = await install_deb(deb_path, pkg.pre_install, pkg.post_install)
    result.old_version = local_version
    result.new_version = latest_version
    return result


@router.post("/api/upgrade/{name}")
async def api_upgrade_package(name: str):
    """更新单个软件包 API（同步等待完成，适合脚本调用）"""
    pkg = config.get_package(name)
    if not pkg:
        raise HTTPException(status_code=404, detail=f"软件包 {name} 不存在")

    result = await _upgrade_one(pkg)
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
        await websocket.send_json({
            "status": "checking",
            "message": "正在获取版本信息...",
        })

        local_version = await asyncio.to_thread(get_installed_version, pkg.name)
        latest_version, download_url = await github_service.get_version_and_url(
            pkg.repo, pkg.asset_pattern
        )

        if not latest_version:
            await websocket.send_json({
                "status": "error",
                "message": "无法获取最新版本（请检查网络或 GitHub Token）",
            })
            await websocket.close()
            return

        if not download_url:
            await websocket.send_json({
                "status": "error",
                "message": f"未找到匹配模式的 deb: {pkg.asset_pattern}",
            })
            await websocket.close()
            return

        if not is_update_needed(local_version, latest_version):
            await websocket.send_json({
                "status": "completed",
                "message": f"已是最新版本 ({latest_version})",
            })
            await websocket.close()
            return

        await websocket.send_json({
            "status": "downloading",
            "message": f"正在下载 {latest_version}...",
            "progress": 0,
        })

        async def progress_callback(downloaded, total, progress):
            try:
                await websocket.send_json({
                    "status": "downloading",
                    "message": f"正在下载 {latest_version}... ({progress}%)",
                    "progress": progress,
                })
            except Exception:
                pass

        deb_path = await download_deb(
            download_url, pkg.name, latest_version, progress_callback
        )

        if not deb_path:
            await websocket.send_json({"status": "error", "message": "下载失败"})
            await websocket.close()
            return

        await websocket.send_json({
            "status": "installing",
            "message": "正在安装（dpkg，可能需要 sudo 权限）...",
            "progress": 100,
        })

        result = await install_deb(deb_path, pkg.pre_install, pkg.post_install)

        if result.success:
            await websocket.send_json({
                "status": "completed",
                "message": f"更新成功: {local_version or '未安装'} → {latest_version}",
            })
        else:
            await websocket.send_json({
                "status": "error",
                "message": f"安装失败: {result.message}",
            })

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
