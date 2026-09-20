#!/bin/bash
# github.sh - GitHub API 交互函数库
# 版本: 1.1

# GitHub API 基础 URL
readonly GITHUB_API_BASE="https://api.github.com"

# 发送 GitHub API 请求（带重试和超时）
# 返回: "http_code|response_body"
_github_api_request() {
    local url="$1"
    local max_retries="${2:-3}"
    local timeout="${3:-15}"

    local curl_headers=()
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl_headers=(-H "Accept: application/vnd.github.v3+json" -H "Authorization: Bearer ${GITHUB_TOKEN}")
    else
        curl_headers=(-H "Accept: application/vnd.github.v3+json")
    fi

    local attempt=0
    local response http_code

    while (( attempt < max_retries )); do
        attempt=$((attempt + 1))

        response=$(curl -s -w "\n%{http_code}" --connect-timeout "$timeout" --max-time "$((timeout * 2))" "${curl_headers[@]}" "$url" 2>/dev/null) || true
        http_code=$(echo "$response" | tail -n1)
        response=$(echo "$response" | sed '$d')

        # 成功或明确的业务错误（404等），不重试
        if [[ "$http_code" =~ ^(200|404)$ ]]; then
            echo "${http_code}|${response}"
            return 0
        fi

        # 速率限制（403/429），等待后重试
        if [[ "$http_code" =~ ^(403|429)$ ]]; then
            if (( attempt < max_retries )); then
                local wait=$((attempt * 5))
                log_warn "GitHub API 速率限制（$url），${wait}秒后重试 ($attempt/$max_retries)..."
                sleep "$wait"
                continue
            fi
            echo "${http_code}|${response}"
            return 0
        fi

        # 网络错误（000等），等待后重试
        if (( attempt < max_retries )); then
            local wait=$((attempt * 2))
            log_warn "GitHub API 请求失败 (HTTP $http_code)，${wait}秒后重试 ($attempt/$max_retries)..."
            sleep "$wait"
            continue
        fi

        echo "${http_code}|${response}"
        return 0
    done
}

# 获取最新 Release 的 tag_name
github_get_latest_release_tag() {
    local repo="$1"
    local url="${GITHUB_API_BASE}/repos/${repo}/releases/latest"

    log_debug "请求 GitHub API: $url"

    local result
    result=$(_github_api_request "$url")
    local http_code="${result%%|*}"
    local response="${result#*|}"

    case "$http_code" in
        200)
            local tag_name
            tag_name=$(echo "$response" | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)

            if [[ -z "$tag_name" ]]; then
                log_warn "无法从 $repo 的响应中提取 tag_name"
                return 1
            fi

            local version="${tag_name#v}"
            echo "$version"
            return 0
            ;;
        403|429)
            log_warn "GitHub API 速率限制已触发（仓库: $repo）。请配置 GITHUB_TOKEN 环境变量以提高速率限制。"
            return 1
            ;;
        404)
            log_error "仓库不存在或无法访问: $repo (HTTP 404)"
            return 1
            ;;
        000)
            log_error "GitHub API 网络连接失败（仓库: $repo），请检查网络"
            return 1
            ;;
        *)
            log_error "GitHub API 请求失败（仓库: $repo，HTTP 状态码: $http_code）"
            return 1
            ;;
    esac
}

# 获取最新且包含匹配资产的正式 Release
# 输出: "version|download_url"
github_get_latest_compatible_release() {
    local repo="$1"
    local asset_pattern="$2"
    local url="${GITHUB_API_BASE}/repos/${repo}/releases?per_page=20"

    log_debug "获取 $repo 的兼容 Release，匹配模式: $asset_pattern"

    local result
    result=$(_github_api_request "$url")
    local http_code="${result%%|*}"
    local response="${result#*|}"

    case "$http_code" in
        200)
            ;;
        403|429)
            log_warn "GitHub API 速率限制已触发（仓库: $repo）。请配置 GITHUB_TOKEN 环境变量以提高速率限制。"
            return 1
            ;;
        000)
            log_error "GitHub API 网络连接失败（仓库: $repo），请检查网络"
            return 1
            ;;
        *)
            log_error "无法获取 $repo 的 Release 信息 (HTTP $http_code)"
            return 1
            ;;
    esac

    local compatible_release
    compatible_release=$(python3 -c '
import fnmatch
import json
import sys

pattern = sys.argv[1]
try:
    releases = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    sys.exit(2)

for release in releases:
    if release.get("draft") or release.get("prerelease"):
        continue
    for asset in release.get("assets", []):
        if fnmatch.fnmatchcase(asset.get("name", ""), pattern):
            tag = release.get("tag_name", "")
            version = tag[1:] if tag.startswith("v") else tag
            url = asset.get("browser_download_url", "")
            if version and url:
                if sys.argv[2] == "metadata":
                    asset_id = asset.get("id", 0)
                    size = asset.get("size", 0)
                    updated = asset.get("updated_at") or ""
                    print(f"{version}|{url}|{asset_id}|{size}|{updated}")
                else:
                    print(f"{version}|{url}")
                sys.exit(0)
sys.exit(1)
' "$asset_pattern" "${3:-}" <<< "$response") || true

    if [[ -z "$compatible_release" ]]; then
        log_warn "在 $repo 最近的正式 Release 中未找到匹配 '$asset_pattern' 的资产"
        return 1
    fi

    log_debug "找到兼容 Release: ${compatible_release%%|*}"
    echo "$compatible_release"
}

# 获取匹配 asset_pattern 的下载 URL
github_get_asset_url() {
    local repo="$1"
    local asset_pattern="$2"
    local compatible_release
    compatible_release=$(github_get_latest_compatible_release "$repo" "$asset_pattern") || return 1
    echo "${compatible_release#*|}"
}
