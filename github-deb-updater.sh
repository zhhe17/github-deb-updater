#!/bin/bash
# github-deb-updater.sh - GitHub deb 软件自动更新工具
# 版本: 1.0

set -e

# 获取脚本所在目录（解析符号链接）
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# 设置库路径
LIB_DIR="${SCRIPT_DIR}/lib"

# 导入库文件
source "${LIB_DIR}/logger.sh"
source "${LIB_DIR}/github.sh"
source "${LIB_DIR}/version.sh"
source "${LIB_DIR}/installer.sh"
source "${LIB_DIR}/yaml.sh"

# 计算字符串的终端显示宽度（中文/全角字符占2列，ASCII占1列）
dwidth() {
    local s="$1" w=0 i=0 len=${#1}
    while (( i < len )); do
        local c="${s:i:1}"
        local cp
        cp=$(printf '%d' "'$c" 2>/dev/null) || cp=0
        if (( cp >= 0x4E00 && cp <= 0x9FFF )) ||    # CJK统一汉字
           (( cp >= 0x3400 && cp <= 0x4DBF )) ||    # CJK扩展A
           (( cp >= 0xF900 && cp <= 0xFAFF )) ||    # CJK兼容
           (( cp >= 0x3000 && cp <= 0x303F )) ||    # CJK符号和标点
           (( cp >= 0xFF00 && cp <= 0xFF60 )) ||    # 全角ASCII
           (( cp >= 0xFFE0 && cp <= 0xFFE6 )) ||    # 全角符号
           (( cp >= 0xFE30 && cp <= 0xFE4F )) ||    # CJK兼容形式
           (( cp >= 0x20000 && cp <= 0x2FA1F )); then # CJK扩展B+
            w=$((w+2))
        else
            w=$((w+1))
        fi
        i=$((i+1))
    done
    echo "$w"
}

# 重复字符 N 次
repeat_char() {
    local char="$1" count="$2"
    printf "%0.s$char" $(seq 1 "$count")
}

# 打印带边框的行，自动计算填充宽度
# 用法: box_print "内容字符串" [总宽度，默认64]
box_print() {
    local content="$1"
    local total="${2:-64}"
    local inner=$((total - 2))
    local cw
    cw=$(dwidth "$content")
    local pad=$((inner - cw))
    if (( pad < 0 )); then pad=0; fi
    printf "║%s%*s║\n" "$content" "$pad" ""
}

# 打印顶部边框
box_top() {
    local total="${1:-64}"
    echo "╔$(repeat_char '═' $((total - 2)))╗"
}

# 打印中间分隔线
box_sep() {
    local total="${1:-64}"
    echo "╠$(repeat_char '═' $((total - 2)))╣"
}

# 打印底部边框
box_bottom() {
    local total="${1:-64}"
    echo "╚$(repeat_char '═' $((total - 2)))╝"
}

# 默认配置
CONFIG_FILE="${SCRIPT_DIR}/packages.yaml"
DRY_RUN=false
AUTO_YES=false
NO_CACHE=false
VERBOSE=false
TOOL_VERSION="1.0.0"

# 显示帮助信息
show_help() {
    cat << EOF
GitHub deb 软件自动更新工具 (github-deb-updater) v${TOOL_VERSION}

用法: github-deb-updater [命令] [选项]

命令:
  update              检查所有软件的更新（默认命令）
  upgrade             更新所有有新版本的软件
  upgrade <name>      仅更新指定软件
  list                列出名单中所有软件及其当前状态
  add                 交互式向 packages.yaml 添加新软件
  token               保存 GitHub Token 到配置文件（用于 sudo 场景）
  version             显示工具本身的版本信息

选项:
  --config <path>     指定 packages.yaml 路径（默认：脚本同级目录）
  --dry-run           仅检查版本，不执行安装
  --yes, -y           跳过所有确认提示，自动确认
  --token <token>     指定 GitHub Token（也可通过 GITHUB_TOKEN 环境变量）
  --no-cache          下载前强制清除对应缓存
  --verbose           显示详细调试信息
  -h, --help          显示帮助信息

示例:
  github-deb-updater list              # 列出所有软件状态
  github-deb-updater update            # 检查更新
  github-deb-updater upgrade           # 更新所有软件
  github-deb-updater upgrade gh        # 仅更新 gh
  github-deb-updater --dry-run upgrade # 模拟更新，不实际安装
  github-deb-updater token             # 保存 Token（解决 sudo 丢失环境变量问题）

EOF
}

# 显示版本信息
show_version() {
    echo "github-deb-updater v${TOOL_VERSION}"
}

# 列出所有软件状态
cmd_list() {
    log_info "读取配置文件: $CONFIG_FILE"
    
    # 初始化 YAML 解析器
    init_yaml_parser
    
    # 解析配置文件
    local packages_data
    packages_data=$(parse_packages_yaml "$CONFIG_FILE")
    
    if [[ -z "$packages_data" ]]; then
        log_warn "配置文件中没有找到任何软件包"
        return 0
    fi
    
    # 第一遍：收集数据并计算最大显示宽度
    local total=0
    local installed=0
    local not_installed=0
    local lines=()
    local max_w=64

    while IFS='|' read -r name display_name repo asset_pattern pre_install post_install; do
        total=$((total + 1))

        local local_version
        local line
        if ! local_version=$(get_installed_version "$name"); then
            line="  [错误]  $display_name  无法读取本地版本  仓库: $repo"
        elif [[ -n "$local_version" ]]; then
            installed=$((installed + 1))
            line="  [OK]  $display_name  本地版本: $local_version  仓库: $repo"
        else
            not_installed=$((not_installed + 1))
            line="  [--]  $display_name  未安装  仓库: $repo"
        fi

        lines+=("$line")
        local w
        w=$(dwidth "$line")
        if (( w > max_w )); then max_w=$w; fi
    done <<< "$packages_data"

    # 计算标题和汇总行的宽度
    local title="                    软件包状态列表"
    local summary="  总计: $total 个软件包 | 已安装: $installed | 未安装: $not_installed"
    local tw sw
    tw=$(dwidth "$title")
    sw=$(dwidth "$summary")
    if (( tw > max_w )); then max_w=$tw; fi
    if (( sw > max_w )); then max_w=$sw; fi

    # 加上边框宽度（左右各 1 列）
    local box_w=$((max_w + 2))

    # 第二遍：输出框
    echo ""
    box_top "$box_w"
    box_print "$title" "$box_w"
    box_sep "$box_w"

    for line in "${lines[@]}"; do
        box_print "$line" "$box_w"
    done

    box_sep "$box_w"
    box_print "$summary" "$box_w"
    box_bottom "$box_w"
    echo ""
}

# 检查所有软件的更新
cmd_update() {
    log_info "开始检查软件更新..."
    
    # 初始化 YAML 解析器
    init_yaml_parser
    
    # 解析配置文件
    local packages_data
    packages_data=$(parse_packages_yaml "$CONFIG_FILE")
    
    if [[ -z "$packages_data" ]]; then
        log_warn "配置文件中没有找到任何软件包"
        return 0
    fi
    
    echo ""
    echo "检查更新中..."
    echo "=========================================="
    
    local total=0
    local update_available=0
    local up_to_date=0
    local errors=0
    
    while IFS='|' read -r name display_name repo asset_pattern pre_install post_install; do
        total=$((total + 1))
        
        log_info "检查 $display_name..."
        
        # 获取本地版本
        local local_version
        if ! local_version=$(get_installed_version "$name"); then
            errors=$((errors + 1))
            continue
        fi
        
        if [[ -n "$local_version" ]]; then
            log_info "  本地版本: $local_version"
        else
            log_info "  未安装"
        fi
        
        # 标签只定位资产；比较必须使用 deb 内部 Version。
        local compatible_release release_version download_url latest_version asset_id asset_size asset_updated
        compatible_release=$(github_get_latest_compatible_release "$repo" "$asset_pattern" metadata) || true
        IFS='|' read -r release_version download_url asset_id asset_size asset_updated <<< "$compatible_release"
        if [[ -z "$release_version" || -z "$download_url" || "$download_url" == "$compatible_release" ]]; then
            log_error "  无法获取最新版本"
            errors=$((errors + 1))
            continue
        fi
        latest_version=$(get_candidate_version "$repo" "$name" "$download_url" "$asset_id" "$asset_size" "$asset_updated") || true
        if [[ -z "$latest_version" ]]; then
            log_error "  无法读取候选 deb 的内部版本"
            errors=$((errors + 1))
            continue
        fi
        log_info "  候选版本: $latest_version (Release: $release_version)"
        
        # 判断是否需要更新
        if is_update_needed "$local_version" "$latest_version"; then
            log_warn "  ⬆ 有新版本可用: ${local_version:-"未安装"} -> $latest_version"
            update_available=$((update_available + 1))
        else
            if [[ $? -eq 2 ]]; then
                log_error "  无法比较版本"
                errors=$((errors + 1))
            else
                log_success "  ✓ 已是最新版本"
                up_to_date=$((up_to_date + 1))
            fi
        fi
        
        echo ""
    done <<< "$packages_data"
    
    echo "=========================================="
    echo "检查完成: 总计 $total | 可更新 $update_available | 已是最新 $up_to_date | 错误 $errors"
}

# 更新软件
cmd_upgrade() {
    local target_package="$1"
    
    log_info "开始更新软件..."
    
    # 初始化 YAML 解析器
    init_yaml_parser
    
    # 解析配置文件
    local packages_data
    packages_data=$(parse_packages_yaml "$CONFIG_FILE")
    
    if [[ -z "$packages_data" ]]; then
        log_warn "配置文件中没有找到任何软件包"
        return 0
    fi
    
    # 统计变量
    local total=0
    local updated=0
    local skipped=0
    local failed=0
    local updated_list=()
    local skipped_list=()
    local failed_list=()
    
    while IFS='|' read -r name display_name repo asset_pattern pre_install post_install; do
        # 如果指定了目标包，只更新该包
        if [[ -n "$target_package" ]] && [[ "$name" != "$target_package" ]]; then
            continue
        fi
        
        total=$((total + 1))
        
        log_info "处理 $display_name..."
        
        # 获取本地版本
        local local_version
        if ! local_version=$(get_installed_version "$name"); then
            failed=$((failed + 1))
            failed_list+=("$display_name: 无法读取本地版本")
            continue
        fi
        
        # 版本和 URL 来自同一资产，更新判断使用 deb 内部 Version。
        local compatible_release release_version latest_version download_url deb_path asset_id asset_size asset_updated
        compatible_release=$(github_get_latest_compatible_release "$repo" "$asset_pattern" metadata) || true
        IFS='|' read -r release_version download_url asset_id asset_size asset_updated <<< "$compatible_release"
        if [[ -z "$release_version" || -z "$download_url" || "$download_url" == "$compatible_release" ]]; then
            log_error "无法获取 $display_name 的最新版本"
            failed=$((failed + 1))
            failed_list+=("$display_name: 无法获取最新版本")
            continue
        fi

        latest_version=$(get_candidate_version "$repo" "$name" "$download_url" "$asset_id" "$asset_size" "$asset_updated") || true
        if [[ -z "$latest_version" ]]; then
            log_error "无法读取 $display_name 候选 deb 的内部版本"
            failed=$((failed + 1))
            failed_list+=("$display_name: deb 元数据无效或包名不匹配")
            continue
        fi
        
        # 判断是否需要更新
        local comparison_result=0
        is_update_needed "$local_version" "$latest_version" || comparison_result=$?
        if [[ $comparison_result -eq 2 ]]; then
            log_error "$display_name 无法比较版本"
            failed=$((failed + 1))
            failed_list+=("$display_name: 无法比较版本")
            continue
        elif [[ $comparison_result -eq 1 ]]; then
            log_success "$display_name 已是最新版本 ($local_version)"
            skipped=$((skipped + 1))
            skipped_list+=("$display_name: $local_version (已是最新)")
            continue
        fi
        
        # 显示更新信息
        if [[ -n "$local_version" ]]; then
            log_info "发现新版本: $local_version -> $latest_version"
        else
            log_info "发现新版本，开始安装: $latest_version"
        fi
        
        # dry-run 模式
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] 将会下载并安装 $display_name $latest_version"
            updated=$((updated + 1))
            updated_list+=("$display_name: ${local_version:-"未安装"} -> $latest_version [DRY-RUN]")
            continue
        fi
        
        # 确认安装
        if [[ "$AUTO_YES" != true ]]; then
            read -p "是否安装 $display_name $latest_version? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "跳过 $display_name"
                skipped=$((skipped + 1))
                skipped_list+=("$display_name: 用户跳过")
                continue
            fi
        fi
        
        # 安装 deb 包
        local verified_candidate verified_version
        if ! verified_candidate=$(get_candidate_version "$repo" "$name" "$download_url" "$asset_id" "$asset_size" "$asset_updated" install); then
            failed=$((failed + 1))
            failed_list+=("$display_name: 安装前候选包校验失败")
            continue
        fi
        IFS='|' read -r verified_version deb_path <<< "$verified_candidate"
        if ! version_compare "$verified_version" "$latest_version"; then
            log_error "$display_name 安装包版本与检查结果不一致"
            failed=$((failed + 1))
            failed_list+=("$display_name: 安装包版本与检查结果不一致")
            continue
        fi
        if install_deb "$deb_path" "$pre_install" "$post_install"; then
            local installed_after
            if installed_after=$(get_installed_version "$name") && [[ -n "$installed_after" ]] && version_compare "$installed_after" "$latest_version"; then
                log_success "$display_name 更新完成并通过版本复核 ($installed_after)"
                updated=$((updated + 1))
                updated_list+=("$display_name: ${local_version:-"未安装"} -> $installed_after")
            else
                log_error "$display_name 安装命令完成，但版本复核失败（期望 $latest_version，实际 ${installed_after:-未安装}）"
                failed=$((failed + 1))
                failed_list+=("$display_name: 安装后版本复核失败")
            fi
        else
            log_error "$display_name 安装失败"
            failed=$((failed + 1))
            failed_list+=("$display_name: 安装失败")
        fi
        
        echo ""
    done <<< "$packages_data"
    
    # 清理旧缓存
    cleanup_cache
    
    # 输出汇总报告（动态计算框宽）
    local report_lines=()
    local max_w=64

    local title="                    更新完成 - 汇总报告"
    report_lines+=("$title")
    local w
    w=$(dwidth "$title"); (( w > max_w )) && max_w=$w

    local line_ok="  [OK]   已更新: ${updated} 个"
    report_lines+=("$line_ok")
    w=$(dwidth "$line_ok"); (( w > max_w )) && max_w=$w

    if [[ $updated -gt 0 ]]; then
        for item in "${updated_list[@]}"; do
            local dl="           - $item"
            report_lines+=("$dl")
            w=$(dwidth "$dl"); (( w > max_w )) && max_w=$w
        done
    fi

    local line_skip="  [SKIP] 已跳过: ${skipped} 个（已是最新版）"
    report_lines+=("$line_skip")
    w=$(dwidth "$line_skip"); (( w > max_w )) && max_w=$w

    if [[ $skipped -gt 0 ]] && [[ $skipped -le 5 ]]; then
        for item in "${skipped_list[@]}"; do
            local dl="           - $item"
            report_lines+=("$dl")
            w=$(dwidth "$dl"); (( w > max_w )) && max_w=$w
        done
    fi

    local line_fail="  [FAIL] 失败: ${failed} 个"
    report_lines+=("$line_fail")
    w=$(dwidth "$line_fail"); (( w > max_w )) && max_w=$w

    if [[ $failed -gt 0 ]]; then
        for item in "${failed_list[@]}"; do
            local dl="           - $item"
            report_lines+=("$dl")
            w=$(dwidth "$dl"); (( w > max_w )) && max_w=$w
        done
    fi

    local box_w=$((max_w + 2))

    echo ""
    box_top "$box_w"
    local first=true
    for line in "${report_lines[@]}"; do
        if [[ "$first" == true ]]; then
            box_print "$line" "$box_w"
            box_sep "$box_w"
            first=false
        else
            box_print "$line" "$box_w"
        fi
    done
    box_bottom "$box_w"
    echo ""
}

# 交互式添加新软件
cmd_add() {
    log_info "交互式添加新软件到配置文件"
    
    echo ""
    echo "请输入以下信息（按 Enter 使用默认值）："
    echo ""
    
    read -p "软件包名称 (用于 dpkg -l 查询): " name
    if [[ -z "$name" ]]; then
        log_error "软件包名称不能为空"
        return 1
    fi
    
    read -p "显示名称 [$name]: " display_name
    display_name="${display_name:-$name}"
    
    read -p "GitHub 仓库 (owner/repo): " repo
    if [[ -z "$repo" ]]; then
        log_error "GitHub 仓库不能为空"
        return 1
    fi
    
    read -p "资产匹配模式 (如: *.deb): " asset_pattern
    if [[ -z "$asset_pattern" ]]; then
        log_error "资产匹配模式不能为空"
        return 1
    fi
    
    read -p "安装前命令 (可选): " pre_install
    read -p "安装后命令 (可选): " post_install
    
    echo ""
    echo "确认添加以下软件包:"
    echo "  名称: $name"
    echo "  显示名称: $display_name"
    echo "  仓库: $repo"
    echo "  资产模式: $asset_pattern"
    [[ -n "$pre_install" ]] && echo "  安装前命令: $pre_install"
    [[ -n "$post_install" ]] && echo "  安装后命令: $post_install"
    echo ""
    
    read -p "确认添加? (y/N) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "已取消添加"
        return 0
    fi
    
    # 添加到配置文件
    cat >> "$CONFIG_FILE" << EOF

  - name: "$name"
    display_name: "$display_name"
    repo: "$repo"
    asset_pattern: "$asset_pattern"
EOF
    
    [[ -n "$pre_install" ]] && echo "    pre_install: \"$pre_install\"" >> "$CONFIG_FILE"
    [[ -n "$post_install" ]] && echo "    post_install: \"$post_install\"" >> "$CONFIG_FILE"
    
    log_success "已成功添加 $display_name 到配置文件"
}

# 保存 GitHub Token 到配置文件
cmd_token() {
    local token_file="${CONFIG_FILE%/*}/.token"

    echo ""
    echo "此命令将 GitHub Token 保存到 ${token_file}"
    echo "解决 sudo 运行时环境变量丢失的问题。"
    echo ""

    local token=""
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        echo "检测到当前环境变量 GITHUB_TOKEN: ${GITHUB_TOKEN:0:8}...${GITHUB_TOKEN: -4}"
        read -p "是否使用此 Token? (Y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            token="$GITHUB_TOKEN"
        fi
    fi

    if [[ -z "$token" ]]; then
        read -p "请输入 GitHub Token: " token
    fi

    if [[ -z "$token" ]]; then
        log_error "Token 不能为空"
        return 1
    fi

    echo "$token" > "$token_file"
    chmod 600 "$token_file"
    log_success "Token 已保存到 $token_file（权限 600）"
    echo "现在可以直接使用 sudo github-deb-updater upgrade，无需额外参数。"
}

# 主函数
main() {
    # 解析命令行参数
    local command=""
    local target_package=""
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            update|list|version|add|token)
                command="$1"
                shift
                ;;
            upgrade)
                command="$1"
                shift
                # 检查是否有目标包名
                if [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; then
                    target_package="$1"
                    shift
                fi
                ;;
            --config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --yes|-y)
                AUTO_YES=true
                shift
                ;;
            --token)
                GITHUB_TOKEN="$2"
                shift 2
                ;;
            --no-cache)
                NO_CACHE=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                export VERBOSE=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 默认命令
    if [[ -z "$command" ]]; then
        command="update"
    fi

    # 如果通过 sudo 运行且未指定 token，尝试从原始用户环境中获取
    if [[ -z "${GITHUB_TOKEN:-}" ]] && [[ -n "${SUDO_USER:-}" ]]; then
        local user_token
        user_token=$(sudo -u "$SUDO_USER" bash -c 'echo "$GITHUB_TOKEN"' 2>/dev/null)
        if [[ -n "$user_token" ]]; then
            GITHUB_TOKEN="$user_token"
            log_debug "已从用户 $SUDO_USER 的环境中获取 GITHUB_TOKEN"
        fi
    fi

    # 如果仍然没有 token，尝试从配置文件读取
    if [[ -z "${GITHUB_TOKEN:-}" ]]; then
        local token_file="${CONFIG_FILE%/*}/.token"
        if [[ -f "$token_file" ]]; then
            GITHUB_TOKEN=$(cat "$token_file" | tr -d '[:space:]')
            log_debug "已从 $token_file 读取 GITHUB_TOKEN"
        fi
    fi

    # 设置日志目录
    LOG_DIR="${SCRIPT_DIR}/logs"
    CACHE_DIR="${SCRIPT_DIR}/cache"
    
    # 确保目录存在
    mkdir -p "$LOG_DIR" "$CACHE_DIR" 2>/dev/null
    
    # 执行命令
    case "$command" in
        list)
            cmd_list
            ;;
        update)
            cmd_update
            ;;
        upgrade)
            cmd_upgrade "$target_package"
            ;;
        add)
            cmd_add
            ;;
        token)
            cmd_token
            ;;
        version)
            show_version
            ;;
        *)
            log_error "未知命令: $command"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
