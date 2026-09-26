"""配置加载模块"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AppConfig(BaseModel):
    github_token: str = ""
    cache_dir: str = "cache"
    log_dir: str = "logs"
    packages_file: str = "packages.yaml"
    auto_check_interval: int = 3600
    server: ServerConfig = ServerConfig()


class PackageConfig(BaseModel):
    """软件包配置。

    source 决定"最新 deb 指针"从哪里解析：
    - github（默认）: repo + asset_pattern 定位 GitHub Release 资产
    - url:    官网固定的 latest 下载链接
    - feed:   厂商 JSON 配置接口 + 点分取值路径
    - scrape: 抓取下载页面，用 asset_pattern 从页面链接中筛选
    """

    name: str
    display_name: str = ""
    repo: str = ""
    asset_pattern: str = ""
    pre_install: str = ""
    post_install: str = ""
    source: str = "github"
    url: str = ""
    feed_url: str = ""
    feed_path: str = ""
    page_url: str = ""
    sign_command: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.display_name:
            self.display_name = self.name
        if not self.source:
            self.source = "github"

    @property
    def browse_url(self) -> str:
        """前端"前往发布页"链接。"""
        if (self.source or "github") == "github" and self.repo:
            return f"https://github.com/{self.repo}/releases"
        return self.page_url or self.url or self.feed_url or ""


class Config:
    """配置管理器"""

    def __init__(self, config_path: str = "config.yaml"):
        self.base_dir = Path(__file__).parent.parent
        self.config_path = self.base_dir / config_path
        self.app_config = self._load_app_config()
        self.packages: list[PackageConfig] = []
        self._load_packages()

    def _load_app_config(self) -> AppConfig:
        """加载应用配置"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        # 环境变量覆盖
        env_token = os.environ.get("GITHUB_TOKEN")
        if env_token:
            data["github_token"] = env_token

        return AppConfig(**data)

    def _load_packages(self):
        """加载软件包配置"""
        packages_path = self.base_dir / self.app_config.packages_file
        if not packages_path.exists():
            return

        with open(packages_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        packages = data.get("packages", [])
        self.packages = [PackageConfig(**pkg) for pkg in packages]

    def get_package(self, name: str) -> Optional[PackageConfig]:
        """获取指定软件包配置"""
        for pkg in self.packages:
            if pkg.name == name:
                return pkg
        return None

    def save_packages(self):
        """保存软件包配置"""
        packages_path = self.base_dir / self.app_config.packages_file
        data = {
            "packages": [pkg.model_dump(exclude_none=True) for pkg in self.packages]
        }
        with open(packages_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    @property
    def cache_path(self) -> Path:
        """缓存目录路径"""
        path = self.base_dir / self.app_config.cache_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_path(self) -> Path:
        """日志目录路径"""
        path = self.base_dir / self.app_config.log_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


# 全局配置实例
config = Config()
