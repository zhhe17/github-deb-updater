#!/bin/bash
# installer.sh - 下载与安装函数库
# 版本: 1.0

# 缓存目录（由主脚本设置）
CACHE_DIR="${CACHE_DIR:-cache}"

# 仅检查时可复用元数据；安装路径总是重新下载/校验。
get_candidate_version() {
    local repo="$1" name="$2" url="$3" asset_id="$4" size="$5" updated="$6" mode="${7:-check}"
    local helper="${SCRIPT_DIR}/app/services/metadata_cache.py"
    local key architecture version deb_path internal_architecture
    key=$(python3 "$helper" key "$repo" "$asset_id" "$size" "$updated" "$url") || return 1
    architecture=$(dpkg --print-architecture) || return 1
    [[ -n "$architecture" ]] || return 1
    if [[ "$mode" == check && "${NO_CACHE:-false}" != true ]]; then
        if version=$(python3 "$helper" read "$CACHE_DIR" "$key" "$name" "$architecture") && validate_version "$version"; then
            printf '%s\n' "$version"
            return 0
        fi
    fi
    if [[ "${NO_CACHE:-false}" == true ]]; then
        rm -f "${CACHE_DIR}/${name}_${key}.deb"
    fi
    deb_path=$(download_deb "$url" "$name" "$key") || return 1
    if [[ "$size" -gt 0 && "$(stat -c %s "$deb_path")" != "$size" ]]; then
        log_error "deb 文件大小与 GitHub 资产不符"
        rm -f "$deb_path"
        return 1
    fi
    version=$(get_deb_package_version "$deb_path" "$name") || return 1
    validate_version "$version" || return 1
    internal_architecture=$(dpkg-deb -f "$deb_path" Architecture) || return 1
    if [[ "$internal_architecture" != "$architecture" && "$internal_architecture" != all ]]; then
        log_error "deb 架构与当前系统不匹配"
        return 1
    fi
    python3 "$helper" write "$CACHE_DIR" "$key" "$name" "$internal_architecture" "$version" || return 1
    if [[ "$mode" == install ]]; then
        printf '%s|%s\n' "$version" "$deb_path"
    else
        printf '%s\n' "$version"
    fi
}

# 读取候选 deb 的真实版本，并确认内部包名与配置一致。
get_deb_package_version() {
    local deb_path="$1"
    local expected_package="$2"
    local internal_package internal_version
    internal_package=$(dpkg-deb -f "$deb_path" Package 2>/dev/null) || return 1
    internal_version=$(dpkg-deb -f "$deb_path" Version 2>/dev/null) || return 1
    if [[ "$internal_package" != "$expected_package" || -z "$internal_version" ]]; then
        log_error "deb 内部包名 '$internal_package' 与配置 '$expected_package' 不一致"
        return 1
    fi
    printf '%s\n' "$internal_version"
}

# 下载 deb 包
download_deb() {
    local url="$1"
    local package_name="$2"
    local version="$3"
    local safe_version="${version//\//_}"
    local target_path="${CACHE_DIR}/${package_name}_${safe_version}.deb"
    
    # 确保缓存目录存在
    mkdir -p "$CACHE_DIR" 2>/dev/null
    
    # 检查文件是否已存在且完整
    if [[ -f "$target_path" ]]; then
        log_info "缓存中已存在 $target_path，验证完整性..."
        if dpkg-deb --info "$target_path" &>/dev/null; then
            log_info "缓存文件完整，跳过下载"
            # 只有文件路径输出到 stdout
            echo "$target_path"
            return 0
        else
            log_warn "缓存文件损坏，重新下载"
            rm -f "$target_path"
        fi
    fi
    
    log_info "下载 $package_name ($version)..."
    log_debug "下载 URL: $url"
    log_debug "保存路径: $target_path"
    
    # 使用 curl 下载
    if ! curl -fsSL --progress-bar -o "$target_path" "$url"; then
        log_error "下载失败: $url"
        rm -f "$target_path"
        return 1
    fi
    
    # 验证 deb 包完整性
    log_info "验证下载文件完整性..."
    if ! dpkg-deb --info "$target_path" &>/dev/null; then
        log_error "下载的 deb 包验证失败（文件可能损坏）"
        rm -f "$target_path"
        return 1
    fi
    
    log_success "下载完成: $target_path"
    # 只有文件路径输出到 stdout
    echo "$target_path"
    return 0
}

# 安装 deb 包
install_deb() {
    local deb_path="$1"
    local pre_install_cmd="${2:-}"
    local post_install_cmd="${3:-}"
    
    # 检查 deb 文件是否存在
    if [[ ! -f "$deb_path" ]]; then
        log_error "安装文件不存在: $deb_path"
        return 1
    fi
    
    # 执行前置命令
    if [[ -n "$pre_install_cmd" ]]; then
        log_info "执行安装前命令: $pre_install_cmd"
        if ! eval "$pre_install_cmd"; then
            log_error "安装前命令执行失败"
            return 1
        fi
    fi
    
    # 使用 dpkg -i 安装
    log_info "安装 $deb_path..."
    if sudo dpkg -i "$deb_path" 2>&1; then
        log_success "dpkg 安装成功"
    else
        # dpkg 可能报告缺少依赖
        log_warn "dpkg 报告缺少依赖，尝试自动修复..."
        
        # 使用 apt-get install -f 修复依赖
        if sudo apt-get install -f -y 2>&1; then
            log_success "依赖修复完成"
        else
            log_error "依赖修复失败"
            return 1
        fi
    fi
    
    # 执行后置命令
    if [[ -n "$post_install_cmd" ]]; then
        log_info "执行安装后命令: $post_install_cmd"
        if ! eval "$post_install_cmd"; then
            log_error "安装后命令执行失败"
            return 1
        fi
    fi
    
    return 0
}

# 清理旧缓存文件
cleanup_cache() {
    if [[ ! -d "$CACHE_DIR" ]]; then
        return 0
    fi
    
    local count
    count=$(find "$CACHE_DIR" -name "*.deb" -mtime +7 2>/dev/null | wc -l)
    
    if [[ $count -gt 0 ]]; then
        log_info "清理 $count 个超过 7 天的缓存文件..."
        find "$CACHE_DIR" -name "*.deb" -mtime +7 -delete 2>/dev/null
        log_success "缓存清理完成"
    else
        log_debug "没有需要清理的旧缓存文件"
    fi
}
