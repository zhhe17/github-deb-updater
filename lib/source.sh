#!/bin/bash
# source.sh - 多来源解析：github / url / feed / scrape
# 版本: 1.0
#
# 输出格式统一为: label|download_url|cache_key|asset_size
# - label:      来源侧的展示标识（GitHub 为 tag 版本，官网源为文件名）
# - cache_key:  元数据缓存身份；官网源由"最终路径+ETag+Last-Modified+大小"构成，
#               与 Web 端 ReleaseInfo 的身份键完全一致，CLI/Web 共享缓存。

_WEB_SOURCE_HELPER="${SCRIPT_DIR}/app/services/web_source.py"
_METADATA_HELPER="${SCRIPT_DIR}/app/services/metadata_cache.py"

# 探测下载地址（跟随重定向），输出: label|最终URL|Content-Length|ETag|Last-Modified
_probe_download_url() {
    local url="$1"
    local probe final_url headers status size etag lastmod path label

    probe=$(curl -sIL -o /dev/null -D - -w '\n%{url_effective}' --max-time 30 "$url" 2>/dev/null) || return 1
    final_url=$(printf '%s\n' "$probe" | tail -n1)
    headers=$(printf '%s\n' "$probe" | sed '$d')
    [[ -n "$final_url" ]] || return 1

    status=$(printf '%s\n' "$headers" | grep -i '^HTTP/' | tail -n1 | awk '{print $2}')
    if [[ "$status" == 405 || "$status" == 501 ]]; then
        # 个别站点拒绝 HEAD（405/501）：回退 GET 只取响应头，与 Web 端
        # _probe 的回退行为保持一致；405 响应体通常极小，丢弃即可。
        probe=$(curl -s -D - -o /dev/null -w '\n%{url_effective}' --max-time 30 "$url" 2>/dev/null) || return 1
        final_url=$(printf '%s\n' "$probe" | tail -n1)
        headers=$(printf '%s\n' "$probe" | sed '$d')
        [[ -n "$final_url" ]] || return 1
        status=$(printf '%s\n' "$headers" | grep -i '^HTTP/' | tail -n1 | awk '{print $2}')
    fi
    [[ "$status" =~ ^2 ]] || return 1

    size=$(printf '%s\n' "$headers" | tr -d '\r' | grep -i '^content-length:' | tail -n1 | tr -dc '0-9')
    etag=$(printf '%s\n' "$headers" | tr -d '\r' | grep -i '^etag:' | tail -n1 | cut -d' ' -f2-)
    lastmod=$(printf '%s\n' "$headers" | tr -d '\r' | grep -i '^last-modified:' | tail -n1 | cut -d' ' -f2-)

    # 身份路径与 Web 端 urlsplit(final_url).path 保持一致：去掉查询与锚点。
    path=$(printf '%s' "$final_url" | sed -e 's|^[a-zA-Z][a-zA-Z0-9+.-]*://||' -e 's|^[^/]*||' -e 's|[?#].*$||')
    [[ -n "$path" ]] || path="$final_url"
    label="${path##*/}"

    printf '%s|%s|%s|%s|%s\n' "$label" "$final_url" "${size:-0}" "$etag" "$lastmod"
}

# 解析一个软件包的最新 deb 资产
# 用法: resolve_asset <name> <source> <repo> <asset_pattern> <url> <feed_url> <feed_path> <page_url> <sign_command>
# 输出: label|download_url|cache_key|asset_size（失败返回非 0）
resolve_asset() {
    local name="$1" source="${2:-github}" repo="$3" asset_pattern="$4"
    local pkg_url="$5" feed_url="$6" feed_path="$7" page_url="$8" sign_command="$9"
    local url label size etag lastmod path key

    case "$source" in
        github)
            local compatible release_version asset_id updated
            compatible=$(github_get_latest_compatible_release "$repo" "$asset_pattern" metadata) || return 1
            IFS='|' read -r release_version url asset_id size updated <<< "$compatible"
            if [[ -z "$release_version" || -z "$url" || "$url" == "$compatible" ]]; then
                log_error "无法解析 GitHub Release 资产"
                return 1
            fi
            key=$(python3 "$_METADATA_HELPER" key "$repo" "$asset_id" "$size" "$updated" "$url") || return 1
            printf '%s|%s|%s|%s\n' "$release_version" "$url" "$key" "$size"
            ;;
        url)
            url="$pkg_url"
            [[ -n "$url" ]] || { log_error "url 来源缺少 url 配置"; return 1; }
            _resolve_web_asset "$name" "$source" "$url" "$sign_command"
            ;;
        feed)
            [[ -n "$feed_url" && -n "$feed_path" ]] || { log_error "feed 来源缺少 feed_url/feed_path 配置"; return 1; }
            url=$(python3 "$_WEB_SOURCE_HELPER" feed "$feed_url" "$feed_path") || { log_error "feed 解析失败"; return 1; }
            _resolve_web_asset "$name" "$source" "$url" "$sign_command"
            ;;
        scrape)
            [[ -n "$page_url" && -n "$asset_pattern" ]] || { log_error "scrape 来源缺少 page_url/asset_pattern 配置"; return 1; }
            url=$(python3 "$_WEB_SOURCE_HELPER" scrape "$page_url" "$asset_pattern") || { log_error "页面抓取失败"; return 1; }
            _resolve_web_asset "$name" "$source" "$url" "$sign_command"
            ;;
        *)
            log_error "未知的来源类型: $source"
            return 1
            ;;
    esac
}

# url/feed/scrape 三类来源的公共尾部：可选签名钩子 + 身份探测 + 缓存键
_resolve_web_asset() {
    local name="$1" source="$2" url="$3" sign_command="$4"
    local probe label final_url size etag lastmod path key

    if [[ -n "$sign_command" ]]; then
        # 相对路径按安装目录解析，cron 等任意 CWD 下调用都能找到脚本。
        case "$sign_command" in
            /*) ;;
            *) sign_command="${SCRIPT_DIR}/${sign_command}" ;;
        esac
        url=$(SIGN_URL="$url" bash "$sign_command") || { log_error "签名命令执行失败"; return 1; }
        [[ -n "$url" ]] || { log_error "签名命令未输出链接"; return 1; }
    fi

    probe=$(_probe_download_url "$url") || { log_error "下载地址探测失败: $url"; return 1; }
    IFS='|' read -r label final_url size etag lastmod <<< "$probe"

    path=$(printf '%s' "$final_url" | sed -e 's|^[a-zA-Z][a-zA-Z0-9+.-]*://||' -e 's|^[^/]*||' -e 's|[?#].*$||')
    [[ -n "$path" ]] || path="$final_url"
    if [[ -z "$etag" && -z "$lastmod" && ( -z "$size" || "$size" == 0 ) ]]; then
        # 无任何身份头：缓存键退化为纯路径哈希，同一路径发布新版会永久
        # 命中旧元数据；标记 nocache 让检查流程每次取真实版本。
        key="nocache"
    else
        key=$(python3 "$_METADATA_HELPER" webkey "$path" "$etag" "$lastmod" "${size:-0}") || return 1
    fi

    printf '%s|%s|%s|%s\n' "$label" "$url" "$key" "${size:-0}"
}
