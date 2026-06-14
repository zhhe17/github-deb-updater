#!/bin/bash
# install.sh - 一键安装脚本
# 版本: 2.0

set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONFIG_DIR="${HOME}/.config/github-deb-updater"
INSTALL_DIR="/opt/github-deb-updater"

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
BLUE='\033[0;34m'
NC='\033[0m' # No Color

_header_title="         GitHub deb 软件自动更新工具 - 安装程序 v2.0"
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
    
    if ! command -v python3 &>/dev/null; then
        missing_deps+=("python3")
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

# 安装 CLI 版本
install_cli() {
    echo ""
    echo "安装 CLI 版本..."
    
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
    
    echo -e "${GREEN}✓ CLI 版本已安装${NC}"
}

# 安装 Web 版本
install_web() {
    echo ""
    echo "安装 Web 版本..."
    
    # 复制文件到安装目录
    if [[ -d "$INSTALL_DIR" ]]; then
        echo "移除旧的安装目录..."
        sudo rm -rf "$INSTALL_DIR"
    fi
    
    echo "复制文件到 $INSTALL_DIR..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -r "${SCRIPT_DIR}/app" "$INSTALL_DIR/"
    sudo cp -r "${SCRIPT_DIR}/static" "$INSTALL_DIR/"
    sudo cp "${SCRIPT_DIR}/packages.yaml" "$INSTALL_DIR/"
    sudo cp "${SCRIPT_DIR}/config.yaml" "$INSTALL_DIR/"
    sudo cp "${SCRIPT_DIR}/requirements.txt" "$INSTALL_DIR/"
    
    # 安装 Python 依赖
    echo "安装 Python 依赖..."
    sudo pip3 install -r "${SCRIPT_DIR}/requirements.txt" --quiet 2>/dev/null || {
        echo -e "${YELLOW}警告: pip3 安装失败，尝试使用 apt 安装...${NC}"
        sudo apt-get install -y python3-fastapi python3-uvicorn python3-jinja2 python3-httpx python3-yaml python3-packaging 2>/dev/null || {
            echo -e "${RED}错误: 无法安装 Python 依赖${NC}"
            echo "请手动运行: sudo pip3 install -r ${SCRIPT_DIR}/requirements.txt"
            exit 1
        }
    }
    
    # 创建缓存和日志目录
    sudo mkdir -p "$INSTALL_DIR/cache" "$INSTALL_DIR/logs"
    
    # 安装 systemd 服务
    echo "安装 systemd 服务..."
    sudo cp "${SCRIPT_DIR}/github-deb-updater.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    
    echo -e "${GREEN}✓ Web 版本已安装${NC}"
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
        "  CLI 版本:"
        "  github-deb-updater list       列出所有软件状态"
        "  github-deb-updater update     检查更新"
        "  github-deb-updater upgrade    更新所有软件"
        "  github-deb-updater --help     查看帮助"
        ""
        "  Web 版本:"
        "  启动服务: sudo systemctl start github-deb-updater"
        "  访问地址: http://localhost:8000"
        "  API 文档: http://localhost:8000/docs"
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
    
    # 询问安装类型
    echo ""
    echo "请选择安装类型:"
    echo "  1) 仅 CLI 版本（命令行工具）"
    echo "  2) 仅 Web 版本（浏览器界面）"
    echo "  3) 全部安装（CLI + Web）"
    echo ""
    read -p "请输入选项 [1/2/3]: " choice
    
    case "$choice" in
        1)
            install_cli
            ;;
        2)
            install_web
            ;;
        3)
            install_cli
            install_web
            ;;
        *)
            echo -e "${RED}无效选项，使用默认选项 3（全部安装）${NC}"
            install_cli
            install_web
            ;;
    esac
    
    setup_config
    show_completion
}

main "$@"
