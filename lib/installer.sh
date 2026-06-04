#!/bin/bash
# installer.sh - 下载与安装函数库
# 版本: 1.0

# 缓存目录（由主脚本设置）
CACHE_DIR="${CACHE_DIR:-cache}"

# 下载 deb 包
download_deb() {
    local url="$1"
    local package_name="$2"
    local version="$3"
    local target_path="${CACHE_DIR}/${package_name}_${version}.deb"
    
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
