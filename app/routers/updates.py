"""更新操作路由"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import config
from app.models import UpdateResult, InstallProgress
from app.services.github import github_service
from app.services.version import get_installed_version, is_update_needed
from app.services.installer import download_deb, install_deb

router = APIRouter(prefix="/updates", tags=["updates"])
templates = Jinja2Templates(directory="app/templates")


@router.post("/api/upgrade/{name}")
async def api_upgrade_package(name: str):
    """更新单个软件包 API"""
    pkg = config.get_package(name)
    if not pkg:
        raise HTTPException(status_code=404, detail=f"软件包 {name} 不存在")

    # 获取版本信息
    local_version = get_installed_version(pkg.name)
    latest_version, download_url = await github_service.get_version_and_url(
        pkg.repo, pkg.asset_pattern
    )

    if not latest_version:
        raise HTTPException(status_code=400, detail="无法获取最新版本")

    if not download_url:
        raise HTTPException(status_code=400, detail="无法获取下载链接")

    if not is_update_needed(local_version, latest_version):
        return UpdateResult(
            success=True,
            message="已是最新版本",
            package_name=pkg.name,
            old_version=local_version,
            new_version=latest_version,
        )

    # 下载
    deb_path = await download_deb(download_url, pkg.name, latest_version)
    if not deb_path:
        raise HTTPException(status_code=500, detail="下载失败")

    # 安装
    result = await install_deb(deb_path, pkg.pre_install, pkg.post_install)
    result.old_version = local_version
    result.new_version = latest_version

    return result


@router.post("/api/upgrade-all")
async def api_upgrade_all():
    """批量更新所有软件包 API"""
    results = []

    for pkg in config.packages:
        try:
            # 获取版本信息
            local_version = get_installed_version(pkg.name)
            latest_version, download_url = await github_service.get_version_and_url(
                pkg.repo, pkg.asset_pattern
            )

            if not latest_version or not download_url:
                results.append(UpdateResult(
                    success=False,
                    message="无法获取版本信息",
                    package_name=pkg.name,
                ))
                continue

            if not is_update_needed(local_version, latest_version):
                results.append(UpdateResult(
                    success=True,
                    message="已是最新版本",
                    package_name=pkg.name,
                    old_version=local_version,
                    new_version=latest_version,
                ))
                continue

            # 下载
            deb_path = await download_deb(download_url, pkg.name, latest_version)
            if not deb_path:
                results.append(UpdateResult(
                    success=False,
                    message="下载失败",
                    package_name=pkg.name,
                ))
                continue

            # 安装
            result = await install_deb(deb_path, pkg.pre_install, pkg.post_install)
            result.old_version = local_version
            result.new_version = latest_version
            results.append(result)

        except Exception as e:
            results.append(UpdateResult(
                success=False,
                message=str(e),
                package_name=pkg.name,
            ))

    return results


@router.websocket("/ws/upgrade/{name}")
async def websocket_upgrade(websocket: WebSocket, name: str):
    """WebSocket 升级进度推送"""
    await websocket.accept()

    pkg = config.get_package(name)
    if not pkg:
        await websocket.send_json({"status": "error", "message": "软件包不存在"})
        await websocket.close()
        return

    try:
        # 发送状态：获取版本信息
        await websocket.send_json({
            "status": "checking",
            "message": "正在获取版本信息...",
        })

        local_version = get_installed_version(pkg.name)
        latest_version, download_url = await github_service.get_version_and_url(
            pkg.repo, pkg.asset_pattern
        )

        if not latest_version or not download_url:
            await websocket.send_json({"status": "error", "message": "无法获取版本信息"})
            await websocket.close()
            return

        if not is_update_needed(local_version, latest_version):
            await websocket.send_json({
                "status": "completed",
                "message": "已是最新版本",
            })
            await websocket.close()
            return

        # 发送状态：开始下载
        await websocket.send_json({
            "status": "downloading",
            "message": f"正在下载 {latest_version}...",
            "progress": 0,
        })

        # 下载进度回调
        async def progress_callback(downloaded, total, progress):
            await websocket.send_json({
                "status": "downloading",
                "message": f"正在下载 {latest_version}...",
                "progress": progress,
            })

        deb_path = await download_deb(
            download_url, pkg.name, latest_version, progress_callback
        )

        if not deb_path:
            await websocket.send_json({"status": "error", "message": "下载失败"})
            await websocket.close()
            return

        # 发送状态：安装中
        await websocket.send_json({
            "status": "installing",
            "message": "正在安装...",
            "progress": 100,
        })

        # 安装
        result = await install_deb(deb_path, pkg.pre_install, pkg.post_install)

        if result.success:
            await websocket.send_json({
                "status": "completed",
                "message": f"更新成功: {local_version} -> {latest_version}",
            })
        else:
            await websocket.send_json({
                "status": "error",
                "message": f"安装失败: {result.message}",
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"status": "error", "message": str(e)})
        except:
            pass

    try:
        await websocket.close()
    except:
        pass
