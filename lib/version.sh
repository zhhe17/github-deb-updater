#!/bin/bash
# version.sh - 版本比较函数库
# 版本: 1.0

# 获取已安装软件的版本号
get_installed_version() {
    local package_name="$1"
    
    # 使用 dpkg -l 查询已安装的包
    local dpkg_output
    dpkg_output=$(dpkg -l "$package_name" 2>/dev/null)
    
    # 检查是否找到包
    if [[ $? -ne 0 ]] || ! echo "$dpkg_output" | grep -q "^ii"; then
        # 未安装
        echo ""
        return 0
    fi
    
    # 提取版本号（第3列）
    local version
    version=$(echo "$dpkg_output" | grep "^ii" | awk '{print $3}')
    
    # 处理 epoch 前缀（如 2:1.89.1 -> 1.89.1）
    if [[ "$version" =~ ^[0-9]+: ]]; then
        version="${version#*:}"
    fi
    
    echo "$version"
    return 0
}

# 比较两个版本号
# 返回值: 0（相等）、1（a > b）、2（a < b）
version_compare() {
    local version_a="$1"
    local version_b="$2"
    
    # 如果版本号相同，直接返回 0
    if [[ "$version_a" == "$version_b" ]]; then
        return 0
    fi
    
    # 使用 sort -V 进行版本比较
    # sort -V 进行自然版本排序
    local sorted
    sorted=$(printf '%s\n%s\n' "$version_a" "$version_b" | sort -V)
    local first
    first=$(echo "$sorted" | head -n1)
    
    if [[ "$first" == "$version_a" ]]; then
        # a <= b
        if [[ "$version_a" == "$version_b" ]]; then
            return 0
        else
            return 2  # a < b
        fi
    else
        return 1  # a > b
    fi
}

# 判断是否需要更新
# 返回值: 0（需要更新）、1（不需要更新）
is_update_needed() {
    local installed_version="$1"
    local latest_version="$2"
    
    # 如果未安装（installed_version 为空），需要安装
    if [[ -z "$installed_version" ]]; then
        return 0  # 需要更新（安装）
    fi
    
    # 比较版本
    version_compare "$installed_version" "$latest_version"
    local result=$?
    
    # 如果 latest > installed（返回值为2），需要更新
    if [[ $result -eq 2 ]]; then
        return 0  # 需要更新
    else
        return 1  # 不需要更新
    fi
}
