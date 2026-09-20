#!/bin/bash
# version.sh - 版本比较函数库
# 版本: 1.0

# 获取已安装软件的版本号
get_installed_version() {
    local package_name="$1"
    local status_version result=0 status version
    status_version=$(LC_ALL=C dpkg-query -W -f='${db:Status-Abbrev}|${Version}' "$package_name" 2>&1) || result=$?
    if [[ $result -eq 1 && "$status_version" == *"no packages found matching"* ]]; then
        return 0
    fi
    if [[ $result -ne 0 || "$status_version" != ???"|"* ]]; then
        echo "无法读取 $package_name 的本地版本：$status_version" >&2
        return 1
    fi
    status="${status_version%%|*}"
    version="${status_version#*|}"
    if [[ "${status:1:1}" == n || "${status:1:1}" == c ]]; then return 0; fi
    if [[ "${status:1}" != "i " || -z "$version" ]]; then
        echo "无法读取 $package_name 的本地版本：安装状态异常 ($status)" >&2
        return 1
    fi
    echo "$version"
    return 0
}

_normalize_version() {
    # 兼容旧调用：Debian Version 必须原样保留。
    printf '%s\n' "$1"
}

# 比较两个版本号
# 返回值: 0（相等）、1（a > b）、2（a < b）、3（比较失败）
version_compare() {
    local version_a="$1"
    local version_b="$2"

    validate_version "$version_a" && validate_version "$version_b" || return 3
    local operator result
    for operator in gt lt eq; do
        result=0
        dpkg --compare-versions "$version_a" "$operator" "$version_b" || result=$?
        if [[ $result -eq 0 ]]; then
            case "$operator" in gt) return 1;; lt) return 2;; eq) return 0;; esac
        fi
        if [[ $result -ne 1 ]]; then
            echo "无法比较版本：dpkg 执行失败" >&2
            return 3
        fi
    done
    echo "无法比较版本：dpkg 返回结果异常" >&2
    return 3
}

validate_version() {
    if [[ -z "$1" ]] || ! dpkg --validate-version "$1" >/dev/null 2>&1; then
        echo "无法比较版本：非法版本或 dpkg 执行失败 ($1)" >&2
        return 1
    fi
}

# 判断是否需要更新
# 返回值: 0（需要更新）、1（不需要更新）、2（比较失败）
is_update_needed() {
    local installed_version="$1"
    local latest_version="$2"
    
    # 如果未安装（installed_version 为空），需要安装
    if [[ -z "$installed_version" ]]; then
        validate_version "$latest_version" || return 2
        return 0  # 需要更新（安装）
    fi
    
    # 比较版本
    local result=0
    version_compare "$installed_version" "$latest_version" || result=$?
    if [[ $result -eq 3 ]]; then return 2; fi
    
    # 如果 latest > installed（返回值为2），需要更新
    if [[ $result -eq 2 ]]; then
        return 0  # 需要更新
    else
        return 1  # 不需要更新
    fi
}
