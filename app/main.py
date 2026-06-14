"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import config
from app.routers import packages, updates, settings
from app.services.github import github_service
from app.services.installer import cleanup_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    cleanup_cache()
    yield
    # 关闭时
    await github_service.close()


app = FastAPI(
    title="GitHub deb 软件自动更新工具",
    description="一站式管理来自 GitHub Release 的 .deb 软件包",
    version="2.0.0",
    lifespan=lifespan,
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册路由
app.include_router(packages.router)
app.include_router(updates.router)
app.include_router(settings.router)


@app.get("/", include_in_schema=False)
async def root():
    """重定向到软件包列表"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/packages/")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "2.0.0"}
