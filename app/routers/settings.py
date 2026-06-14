"""设置页面路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import config

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置页面"""
    context = {
        "github_token": config.app_config.github_token,
        "auto_check_interval": config.app_config.auto_check_interval,
        "server_host": config.app_config.server.host,
        "server_port": config.app_config.server.port,
    }
    return templates.TemplateResponse(request=request, name="settings.html", context=context)


@router.post("/api/token")
async def api_set_token(token: str):
    """设置 GitHub Token"""
    config.app_config.github_token = token

    # 保存到配置文件
    import yaml
    from pathlib import Path

    config_path = config.config_path
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    data["github_token"] = token

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    # 更新 GitHub 服务的 token
    from app.services.github import github_service
    github_service.token = token
    github_service._client = None  # 重置客户端

    return {"message": "Token 已保存"}


@router.post("/api/interval")
async def api_set_interval(interval: int):
    """设置自动检查间隔"""
    config.app_config.auto_check_interval = interval
    return {"message": f"自动检查间隔已设置为 {interval} 秒"}
