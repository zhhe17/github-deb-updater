#!/bin/bash
# install.sh - 一键安装脚本
# 版本: 1.0

set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONFIG_DIR="${HOME}/.config/github-deb-updater"

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

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

_header_title="         GitHub deb 软件自动更新工具 - 安装程序"
_header_w=$(( $(dwidth "$_header_title") + 2 ))
box_top "$_header_w"
box_print "$_header_title" "$_header_w"
box_bottom "$_header_w"
echo ""

# 检测依赖
check_dependencies() {
    local missing_deps=()
    
    echo "检查系统依赖..."
    
    if ! command -v curl &>/dev/null; then
        missing_deps+=("curl")
    fi
    
    if ! command -v dpkg &>/dev/null; then
        missing_deps+=("dpkg")
    fi
    
    if ! command -v sudo &>/dev/null; then
        missing_deps+=("sudo")
    fi
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        echo -e "${RED}错误: 缺少以下依赖:${NC}"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
        done
        echo ""
        echo "请使用以下命令安装:"
        echo "  sudo apt update && sudo apt install -y ${missing_deps[*]}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ 所有依赖已满足${NC}"
}

# 安装主程序
install_program() {
    echo ""
    echo "安装主程序..."
    
    # 创建符号链接
    local target_link="/usr/local/bin/github-deb-updater"
    local source_script="${SCRIPT_DIR}/github-deb-updater.sh"
    
    # 确保源脚本存在
    if [[ ! -f "$source_script" ]]; then
        echo -e "${RED}错误: 找不到主脚本 $source_script${NC}"
        exit 1
    fi
    
    # 确保源脚本有执行权限
    chmod +x "$source_script"
    
    # 创建符号链接（需要 sudo）
    if [[ -L "$target_link" ]]; then
        echo "移除旧的符号链接..."
        sudo rm -f "$target_link"
    fi
    
    echo "创建符号链接: $target_link -> $source_script"
    sudo ln -s "$source_script" "$target_link"
    
    echo -e "${GREEN}✓ 主程序已安装${NC}"
}

# 创建默认配置
setup_config() {
    echo ""
    echo "设置默认配置..."
    
    # 创建配置目录
    mkdir -p "$CONFIG_DIR"
    
    # 如果配置文件不存在，复制默认配置
    if [[ ! -f "${CONFIG_DIR}/packages.yaml" ]]; then
        cp "${SCRIPT_DIR}/packages.yaml" "${CONFIG_DIR}/packages.yaml"
        echo "已复制默认配置到: ${CONFIG_DIR}/packages.yaml"
    else
        echo "配置文件已存在，跳过复制"
    fi
    
    # 创建符号链接指向配置目录
    if [[ ! -L "${SCRIPT_DIR}/packages.yaml.local" ]]; then
        ln -s "${CONFIG_DIR}/packages.yaml" "${SCRIPT_DIR}/packages.yaml.local"
    fi
    
    echo -e "${GREEN}✓ 配置设置完成${NC}"
}

# 显示安装完成信息
show_completion() {
    local lines=(
        "                    安装完成！"
        ""
        "  您现在可以在任意位置使用以下命令:"
        ""
        "  github-deb-updater list       列出所有软件状态"
        "  github-deb-updater update     检查更新"
        "  github-deb-updater upgrade    更新所有软件"
        "  github-deb-updater --help     查看帮助"
        ""
        "  配置文件位置: ~/.config/github-deb-updater/packages.yaml"
        ""
        "  建议配置 GitHub Token 以提高 API 速率限制:"
        "  export GITHUB_TOKEN=\"your_token_here\""
    )

    local max_w=64
    for line in "${lines[@]}"; do
        local w
        w=$(dwidth "$line")
        (( w > max_w )) && max_w=$w
    done
    local box_w=$((max_w + 2))

    echo ""
    box_top "$box_w"
    for line in "${lines[@]}"; do
        box_print "$line" "$box_w"
    done
    box_bottom "$box_w"
}

# 主函数
main() {
    check_dependencies
    install_program
    setup_config
    show_completion
}

main "$@"
