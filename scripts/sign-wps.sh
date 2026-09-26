#!/bin/bash
# sign-wps.sh - 金山 WPS CDN（wpscdn.cn，kngx 防盗链）签名钩子
# 用法: SIGN_URL=<原始下载地址> bash scripts/sign-wps.sh
# 输出: 附加 ?t=<秒级时间戳>&k=<md5(key+路径+t)> 的签名地址
#
# 算法来自 linux.wps.cn 页面内联脚本：
#   secrityKey = "7f8faaaa468174dc1c9cd62e5f218a5b"
#   k = MD5(secrityKey + urlObj.pathname + timestamp10)

set -euo pipefail

url="${SIGN_URL:?SIGN_URL 未设置}"

python3 - "$url" <<'PY'
import hashlib
import sys
import time
from urllib.parse import urlsplit

url = sys.argv[1]
key = "7f8faaaa468174dc1c9cd62e5f218a5b"
path = urlsplit(url).path
t = int(time.time())
k = hashlib.md5(f"{key}{path}{t}".encode()).hexdigest()
sep = "&" if "?" in url else "?"
print(f"{url}{sep}t={t}&k={k}")
PY
