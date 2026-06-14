"""版本比较服务"""

import re
import subprocess
from typing import Optional

from packaging.version import Version, InvalidVersion


def get_installed_version(package_name: str) -> Optional[str]:
    """获取已安装软件的版本号

    通过 dpkg -l 查询本地已安装的包版本
    """
    try:
        result = subprocess.run(
            ["dpkg", "-l", package_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return None

        # 查找 ii 开头的行（已安装标记）
        for line in result.stdout.splitlines():
            if line.startswith("ii"):
                parts = line.split()
                if len(parts) >= 3:
                    version = parts[2]
                    # 去除 epoch 前缀（如 2:1.89.1 -> 1.89.1）
                    if ":" in version:
                        version = version.split(":", 1)[1]
                    return version

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def normalize_version(version: str) -> str:
    """标准化版本号

    - 去除 + 及其后的构建元数据
    - 去除第 4 段（当恰好 4 段数字时）
    """
    # 去除 + 及其后的构建元数据
    if "+" in version:
        version = version.split("+", 1)[0]

    # 去除第 4 段（当恰好 4 段数字时）
    match = re.match(r"^(\d+\.\d+\.\d+)\.\d+$", version)
    if match:
        version = match.group(1)

    return version


def compare_versions(version_a: str, version_b: str) -> int:
    """比较两个版本号

    Returns:
        0: 相等
        1: a > b
        -1: a < b
    """
    # 标准化
    norm_a = normalize_version(version_a)
    norm_b = normalize_version(version_b)

    # 字符串相等
    if norm_a == norm_b:
        return 0

    try:
        v_a = Version(norm_a)
        v_b = Version(norm_b)

        if v_a > v_b:
            return 1
        elif v_a < v_b:
            return -1
        else:
            return 0
    except InvalidVersion:
        # 无法解析时，使用字符串比较
        if norm_a > norm_b:
            return 1
        elif norm_a < norm_b:
            return -1
        return 0


def is_update_needed(installed_version: Optional[str], latest_version: str) -> bool:
    """判断是否需要更新

    Returns:
        True: 需要更新（未安装或本地版本较旧）
        False: 不需要更新
    """
    # 未安装，需要安装
    if not installed_version:
        return True

    # 比较版本
    return compare_versions(latest_version, installed_version) > 0
