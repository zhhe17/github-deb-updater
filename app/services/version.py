"""使用 Debian 原生语义读取和比较软件包版本。"""

import os
import subprocess
from typing import Optional


class VersionError(RuntimeError):
    """版本读取或比较失败，不能解释为未安装或版本相等。"""


def validate_version(version: str) -> None:
    try:
        result = subprocess.run(
            ["dpkg", "--validate-version", version],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        raise VersionError("无法比较版本：无法调用 dpkg 校验版本") from error
    if not version or result.returncode != 0:
        raise VersionError(f"无法比较版本：非法 Debian 版本 {version!r}")


def get_installed_version(package_name: str) -> Optional[str]:
    """返回 dpkg 中的完整版本，保留 epoch、+build 与 Debian revision。"""
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", package_name],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        raise VersionError(
            f"无法读取 {package_name} 的本地版本：dpkg-query 执行失败"
        ) from error
    if result.returncode == 1 and "no packages found matching" in result.stderr:
        return None
    if result.returncode != 0:
        raise VersionError(
            f"无法读取 {package_name} 的本地版本：{result.stderr.strip()}"
        )
    status, separator, version = result.stdout.rstrip("\n").partition("|")
    if not separator or len(status) != 3:
        raise VersionError(f"无法读取 {package_name} 的本地版本：返回格式异常")
    if status[1] in ("n", "c"):
        return None
    if status[1:] != "i " or not version.strip():
        raise VersionError(
            f"无法读取 {package_name} 的本地版本：安装状态异常 ({status})"
        )
    return version.strip()


def normalize_version(version: str) -> str:
    """兼容旧调用；Debian 版本不得自行裁剪或改写。"""
    return version.strip()


def compare_versions(version_a: str, version_b: str) -> int:
    """比较两个版本号

    Returns:
        0: 相等
        1: a > b
        -1: a < b
    """
    norm_a = normalize_version(version_a)
    norm_b = normalize_version(version_b)
    validate_version(norm_a)
    validate_version(norm_b)
    try:
        for operator, comparison in (("gt", 1), ("lt", -1), ("eq", 0)):
            result = subprocess.run(
                ["dpkg", "--compare-versions", norm_a, operator, norm_b],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return comparison
            if result.returncode != 1:
                raise VersionError(f"无法比较版本：{result.stderr.strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        raise VersionError("无法比较版本：dpkg 执行失败") from error
    raise VersionError("无法比较版本：dpkg 返回不一致的比较结果")


def is_update_needed(installed_version: Optional[str], latest_version: str) -> bool:
    """判断是否需要更新

    Returns:
        True: 需要更新（未安装或本地版本较旧）
        False: 不需要更新
    """
    # 未安装，需要安装
    if installed_version is None:
        validate_version(latest_version)
        return True

    # 比较版本
    return compare_versions(latest_version, installed_version) > 0
