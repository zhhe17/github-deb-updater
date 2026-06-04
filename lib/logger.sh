#!/bin/bash
# logger.sh - 日志输出函数库
# 版本: 1.0

# 颜色定义
readonly COLOR_BLUE='\033[0;34m'
readonly COLOR_GREEN='\033[0;32m'
readonly COLOR_YELLOW='\033[1;33m'
readonly COLOR_RED='\033[0;31m'
readonly COLOR_NC='\033[0m' # No Color

# 日志目录（由主脚本设置）
LOG_DIR="${LOG_DIR:-logs}"

# 获取当前时间戳
_get_timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# 写入日志文件
_write_to_log_file() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(_get_timestamp)
    
    # 确保日志目录存在
    mkdir -p "$LOG_DIR" 2>/dev/null
    
    # 写入日志文件（延迟计算路径）
    echo "[$timestamp] [$level] $message" >> "${LOG_DIR}/update.log" 2>/dev/null
}

# INFO 级别日志 - 蓝色
log_info() {
    local message="$1"
    echo -e "${COLOR_BLUE}[INFO]${COLOR_NC}    $message" >&2
    _write_to_log_file "INFO" "$message"
}

# SUCCESS 级别日志 - 绿色
log_success() {
    local message="$1"
    echo -e "${COLOR_GREEN}[SUCCESS]${COLOR_NC} $message" >&2
    _write_to_log_file "SUCCESS" "$message"
}

# WARN 级别日志 - 黄色
log_warn() {
    local message="$1"
    echo -e "${COLOR_YELLOW}[WARN]${COLOR_NC}    $message" >&2
    _write_to_log_file "WARN" "$message"
}

# ERROR 级别日志 - 红色（输出到 stderr）
log_error() {
    local message="$1"
    echo -e "${COLOR_RED}[ERROR]${COLOR_NC}   $message" >&2
    _write_to_log_file "ERROR" "$message"
}

# DEBUG 级别日志（仅在 verbose 模式下输出）
log_debug() {
    local message="$1"
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo -e "[DEBUG]   $message" >&2
    fi
    _write_to_log_file "DEBUG" "$message"
}
