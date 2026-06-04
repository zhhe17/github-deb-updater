#!/bin/bash
# yaml.sh - YAML 解析函数库
# 版本: 1.0

# YAML 解析方式标记
YAML_PARSER_METHOD=""

# 初始化 YAML 解析器
init_yaml_parser() {
    # 检查 python3 是否可用
    if command -v python3 &>/dev/null; then
        # 检查 PyYAML 是否已安装
        if python3 -c "import yaml" &>/dev/null; then
            YAML_PARSER_METHOD="python"
            log_debug "YAML 解析器: Python + PyYAML"
            return 0
        else
            # 尝试安装 PyYAML
            log_debug "尝试安装 PyYAML..."
            if pip3 install pyyaml --quiet 2>/dev/null; then
                YAML_PARSER_METHOD="python"
                log_debug "YAML 解析器: Python + PyYAML (已安装)"
                return 0
            fi
        fi
    fi
    
    # 降级到 grep/sed/awk 解析
    YAML_PARSER_METHOD="grep"
    log_debug "YAML 解析器: grep/sed/awk (降级方案)"
    return 0
}

# 解析 packages.yaml 并输出结构化数据
# 输出格式（每行）: name|display_name|repo|asset_pattern|pre_install|post_install
parse_packages_yaml() {
    local yaml_file="$1"
    
    if [[ ! -f "$yaml_file" ]]; then
        log_error "配置文件不存在: $yaml_file"
        return 1
    fi
    
    case "$YAML_PARSER_METHOD" in
        python)
            _parse_yaml_python "$yaml_file"
            ;;
        grep)
            _parse_yaml_grep "$yaml_file"
            ;;
        *)
            log_error "YAML 解析器未初始化"
            return 1
            ;;
    esac
}

# 使用 Python 解析 YAML
_parse_yaml_python() {
    local yaml_file="$1"
    
    python3 -c "
import yaml
import sys

try:
    with open('${yaml_file}', 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if not data or 'packages' not in data:
        print('错误: 配置文件格式不正确，缺少 packages 字段', file=sys.stderr)
        sys.exit(1)
    
    packages = data.get('packages', [])
    for pkg in packages:
        name = pkg.get('name', '')
        display_name = pkg.get('display_name', name)
        repo = pkg.get('repo', '')
        asset_pattern = pkg.get('asset_pattern', '')
        pre_install = pkg.get('pre_install', '')
        post_install = pkg.get('post_install', '')
        
        print(f'{name}|{display_name}|{repo}|{asset_pattern}|{pre_install}|{post_install}')

except Exception as e:
    print(f'YAML 解析错误: {e}', file=sys.stderr)
    sys.exit(1)
"
}

# 使用 grep/sed/awk 解析 YAML（降级方案）
_parse_yaml_grep() {
    local yaml_file="$1"
    
    log_debug "使用 grep/sed/awk 解析 YAML"
    
    # 临时变量
    local current_name=""
    local current_display_name=""
    local current_repo=""
    local current_asset_pattern=""
    local current_pre_install=""
    local current_post_install=""
    local in_package=false
    
    # 逐行读取 YAML 文件
    while IFS= read -r line; do
        # 移除注释
        line=$(echo "$line" | sed 's/#.*$//')
        
        # 跳过空行
        [[ -z "$line" ]] && continue
        
        # 检测新包的开始
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*name:[[:space:]]*\"?([^\"]+)\"? ]]; then
            # 输出前一个包（如果存在）
            if [[ -n "$current_name" ]]; then
                echo "${current_name}|${current_display_name}|${current_repo}|${current_asset_pattern}|${current_pre_install}|${current_post_install}"
            fi
            
            # 初始化新包
            current_name="${BASH_REMATCH[1]}"
            current_display_name="$current_name"
            current_repo=""
            current_asset_pattern=""
            current_pre_install=""
            current_post_install=""
            in_package=true
            continue
        fi
        
        # 解析字段
        if [[ "$in_package" == true ]]; then
            if [[ "$line" =~ ^[[:space:]]*display_name:[[:space:]]*\"?([^\"]+)\"? ]]; then
                current_display_name="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ ^[[:space:]]*repo:[[:space:]]*\"?([^\"]+)\"? ]]; then
                current_repo="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ ^[[:space:]]*asset_pattern:[[:space:]]*\"?([^\"]+)\"? ]]; then
                current_asset_pattern="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ ^[[:space:]]*pre_install:[[:space:]]*\"?([^\"]+)\"? ]]; then
                current_pre_install="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ ^[[:space:]]*post_install:[[:space:]]*\"?([^\"]+)\"? ]]; then
                current_post_install="${BASH_REMATCH[1]}"
            fi
        fi
    done < "$yaml_file"
    
    # 输出最后一个包
    if [[ -n "$current_name" ]]; then
        echo "${current_name}|${current_display_name}|${current_repo}|${current_asset_pattern}|${current_pre_install}|${current_post_install}"
    fi
}
