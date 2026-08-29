#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/lib/logger.sh"
source "${ROOT_DIR}/lib/github.sh"

_github_api_request() {
    cat <<'JSON'
200|[
  {
    "tag_name": "v1.18.1",
    "draft": false,
    "prerelease": false,
    "assets": [
      {
        "name": "LocalSend-1.18.1-android-x64.apk",
        "browser_download_url": "https://example.invalid/mobile.apk"
      }
    ]
  },
  {
    "tag_name": "v1.18.0",
    "draft": false,
    "prerelease": false,
    "assets": [
      {
        "name": "LocalSend-1.18.0-linux-x86-64.deb",
        "browser_download_url": "https://example.invalid/localsend.deb"
      }
    ]
  }
]
JSON
}

actual=$(github_get_latest_compatible_release \
    "localsend/localsend" "LocalSend-*-linux-x86-64.deb")
expected="1.18.0|https://example.invalid/localsend.deb"

if [[ "$actual" != "$expected" ]]; then
    echo "expected: $expected" >&2
    echo "actual:   $actual" >&2
    exit 1
fi
