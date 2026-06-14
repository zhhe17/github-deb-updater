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

# 标准化版本号（去除构建元数据和常见前缀）
# 处理格式：
#   desktop-v1.6.0  -> 去除前缀 -> 1.6.0
#   v1.6.0          -> 去除前缀 -> 1.6.0
#   V1.6.0          -> 去除前缀 -> 1.6.0
#   release-1.6.0   -> 去除前缀 -> 1.6.0
#   app-1.6.0       -> 去除前缀 -> 1.6.0
#   1.0.24+1006     -> + 后为构建元数据，去掉 -> 1.0.24
#   1.0.24.1006     -> 四段版本号，最后一段为构建号，去掉 -> 1.0.24
_normalize_version() {
    local version="$1"
    # 去除常见的版本前缀（匹配最后一个 -v 或 _v 之后的内容，或者开头的 v/V）
    # 例如: desktop-v1.6.0 -> 1.6.0, app-v2.0.0 -> 2.0.0
    if [[ "$version" =~ [-_]v?([0-9].*)$ ]]; then
        version="${BASH_REMATCH[1]}"
    elif [[ "$version" =~ ^[vV]([0-9].*)$ ]]; then
        version="${BASH_REMATCH[1]}"
    fi
    # 去除 + 及其后的构建元数据（语义化版本规范）
    version="${version%%+*}"
    # 如果版本号有 4 段或更多，去掉最后一段（构建号）
    # 仅当恰好 4 段且最后一段为纯数字时处理
    if [[ "$version" =~ ^([0-9]+\.[0-9]+\.[0-9]+)\.[0-9]+$ ]]; then
        version="${BASH_REMATCH[1]}"
    fi
    echo "$version"
}

# 比较两个版本号
# 返回值: 0（相等）、1（a > b）、2（a < b）
version_compare() {
    local version_a="$1"
    local version_b="$2"

    # 去除构建元数据
    local norm_a norm_b
    norm_a=$(_normalize_version "$version_a")
    norm_b=$(_normalize_version "$version_b")

    # 标准化后相同，视为相等
    if [[ "$norm_a" == "$norm_b" ]]; then
        return 0
    fi

    # 使用 sort -V 进行版本比较
    local sorted
    sorted=$(printf '%s\n%s\n' "$norm_a" "$norm_b" | sort -V)
    local first
    first=$(echo "$sorted" | head -n1)

    if [[ "$first" == "$norm_a" ]]; then
        return 2  # a < b
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
