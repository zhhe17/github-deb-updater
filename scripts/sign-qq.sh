#!/usr/bin/env bash
# sign-qq.sh - 用 im.qq.com 的 GetSign 接口为 QQ deb 下载链接换取带签名的临时链接。
#
# QQ 的 deb 原始链接托管在 qqdl.gtimg.cn 上，直接请求会被 403 拒绝，
# 必须先向 GetSign 接口换取带 sign 参数的临时链接。
#
# 用法: 在 packages.yaml 中配置 sign_command: scripts/sign-qq.sh
#       工具通过环境变量 SIGN_URL 传入原始链接，脚本向 stdout 输出签名后的链接。
set -euo pipefail

RAW_URL="${SIGN_URL:?未通过环境变量 SIGN_URL 传入待签名链接}"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
COOKIE_URL="https://im.qq.com/index/"
SIGN_URL_API="https://im.qq.com/http2rpc/gotrpc/noauth/trpc.qqntv2.urlsign.UrlSign/GetSign"

# 1. 访问 im.qq.com 首页拿 tgw_l7_route cookie（GetSign 接口要求携带）。
# -o /dev/null 让 stdout 只剩 cookie jar，避免页面正文里的
# tgw_l7_route 字样干扰 awk 取值。
COOKIE=$(curl -fsSL -A "$UA" -c - -o /dev/null "$COOKIE_URL" 2>/dev/null \
    | awk '/tgw_l7_route/ {print $7; exit}')
if [[ -z "$COOKIE" ]]; then
    echo "无法从 $COOKIE_URL 获取 tgw_l7_route cookie" >&2
    exit 1
fi

# 2. 调 GetSign 换取带 sign 的下载链接。
curl -fsSL -A "$UA" \
    -H "Content-Type: application/json" \
    -H "Origin: https://im.qq.com" \
    -H "Referer: https://im.qq.com/index/" \
    -H 'x-oidb: {"uint32_command":"0x9b8e","uint32_service_type":1}' \
    -b "tgw_l7_route=$COOKIE" \
    --data-binary "$(python3 -c 'import json,sys; print(json.dumps({"url": sys.argv[1]}))' "$RAW_URL")" \
    "$SIGN_URL_API" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["url"])'
