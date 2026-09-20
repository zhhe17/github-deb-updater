"""数据模型定义"""

import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PackageStatus(str, Enum):
    """软件包状态"""

    UP_TO_DATE = "up_to_date"  # 已是最新
    UPDATE_AVAILABLE = "update_available"  # 有更新可用
    NOT_INSTALLED = "not_installed"  # 未安装
    ERROR = "error"  # 错误


class PackageInfo(BaseModel):
    """软件包信息"""

    name: str
    display_name: str
    repo: str
    asset_pattern: str
    local_version: Optional[str] = None
    latest_version: Optional[str] = None
    status: PackageStatus = PackageStatus.NOT_INSTALLED
    error_message: Optional[str] = None


class ReleaseInfo(BaseModel):
    """GitHub Release 中一个确定的 deb 资产。"""

    asset_id: int
    tag_name: str
    release_version: str
    asset_name: str
    download_url: str
    asset_size: int = 0
    asset_updated_at: Optional[str] = None

    @property
    def cache_key(self) -> str:
        identity = f"{self.asset_id}|{self.asset_name}|{self.asset_size}|{self.asset_updated_at or ''}"
        digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
        return f"asset-{self.asset_id}-{digest}"


class CandidatePackage(BaseModel):
    """从 deb 自身元数据得到的候选版本。"""

    path: str
    package_name: str
    deb_version: str
    architecture: str
    release: ReleaseInfo


class UpdateResult(BaseModel):
    """更新结果"""

    success: bool
    message: str
    package_name: str
    old_version: Optional[str] = None
    new_version: Optional[str] = None


class CheckResult(BaseModel):
    """检查更新结果"""

    total: int
    up_to_date: int
    update_available: int
    not_installed: int
    errors: int
    packages: list[PackageInfo]
    checked_at: datetime = datetime.now()


class InstallProgress(BaseModel):
    """安装进度"""

    package_name: str
    status: str  # downloading, installing, completed, failed
    progress: int = 0  # 0-100
    message: str = ""
