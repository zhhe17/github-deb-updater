"""软件包管理路由"""

import asyncio
import fnmatch
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import config
from app.models import PackageInfo, PackageStatus, CheckResult
from app.services.github import github_service
from app.services.version import get_installed_version, is_update_needed

router = APIRouter(prefix="/packages", tags=["packages"])
templates = Jinja2Templates(directory="app/templates")


async def _get_package_info(pkg) -> PackageInfo:
    """获取单个软件包信息"""
    info = PackageInfo(
        name=pkg.name,
        display_name=pkg.display_name,
        repo=pkg.repo,
        asset_pattern=pkg.asset_pattern,
    )

    # 获取本地版本
    info.local_version = get_installed_version(pkg.name)

    # 获取最新版本
    try:
        version, url = await github_service.get_version_and_url(pkg.repo, pkg.asset_pattern)
        info.latest_version = version

        if version is None:
            info.status = PackageStatus.ERROR
            info.error_message = "无法获取最新版本"
        elif info.local_version is None:
            info.status = PackageStatus.NOT_INSTALLED
        elif is_update_needed(info.local_version, version):
            info.status = PackageStatus.UPDATE_AVAILABLE
        else:
            info.status = PackageStatus.UP_TO_DATE
    except Exception as e:
        info.status = PackageStatus.ERROR
        info.error_message = str(e)

    return info


@router.get("/", response_class=HTMLResponse)
async def list_packages(request: Request):
    """软件包列表页面"""
    packages = []

    # 并发获取所有软件包信息
    tasks = [_get_package_info(pkg) for pkg in config.packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            continue
        packages.append(result)

    # 统计
    total = len(packages)
    up_to_date = sum(1 for p in packages if p.status == PackageStatus.UP_TO_DATE)
    update_available = sum(1 for p in packages if p.status == PackageStatus.UPDATE_AVAILABLE)
    not_installed = sum(1 for p in packages if p.status == PackageStatus.NOT_INSTALLED)
    errors = sum(1 for p in packages if p.status == PackageStatus.ERROR)

    context = {
        "packages": [p.model_dump() for p in packages],
        "total": total,
        "up_to_date": up_to_date,
        "update_available": update_available,
        "not_installed": not_installed,
        "errors": errors,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@router.get("/api/list")
async def api_list_packages():
    """获取软件包列表 API"""
    packages = []

    tasks = [_get_package_info(pkg) for pkg in config.packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            continue
        packages.append(result.model_dump())

    return {"packages": packages}


@router.get("/api/check")
async def api_check_updates():
    """检查更新 API"""
    packages = []

    tasks = [_get_package_info(pkg) for pkg in config.packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            continue
        packages.append(result)

    total = len(packages)
    up_to_date = sum(1 for p in packages if p.status == PackageStatus.UP_TO_DATE)
    update_available = sum(1 for p in packages if p.status == PackageStatus.UPDATE_AVAILABLE)
    not_installed = sum(1 for p in packages if p.status == PackageStatus.NOT_INSTALLED)
    errors = sum(1 for p in packages if p.status == PackageStatus.ERROR)

    return CheckResult(
        total=total,
        up_to_date=up_to_date,
        update_available=update_available,
        not_installed=not_installed,
        errors=errors,
        packages=packages,
    )


@router.post("/api/add")
async def api_add_package(
    name: str,
    repo: str,
    asset_pattern: str,
    display_name: Optional[str] = None,
    pre_install: Optional[str] = None,
    post_install: Optional[str] = None,
):
    """添加软件包 API"""
    # 检查是否已存在
    if config.get_package(name):
        raise HTTPException(status_code=400, detail=f"软件包 {name} 已存在")

    # 创建新配置
    from app.config import PackageConfig

    new_pkg = PackageConfig(
        name=name,
        display_name=display_name or name,
        repo=repo,
        asset_pattern=asset_pattern,
        pre_install=pre_install or "",
        post_install=post_install or "",
    )

    # 保存
    config.packages.append(new_pkg)
    config.save_packages()

    return {"message": f"成功添加 {new_pkg.display_name}", "package": new_pkg.model_dump()}


@router.delete("/api/{name}")
async def api_delete_package(name: str):
    """删除软件包 API"""
    pkg = config.get_package(name)
    if not pkg:
        raise HTTPException(status_code=404, detail=f"软件包 {name} 不存在")

    config.packages = [p for p in config.packages if p.name != name]
    config.save_packages()

    return {"message": f"成功删除 {pkg.display_name}"}
