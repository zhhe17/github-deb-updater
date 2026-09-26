"""官网 / CDN 类 deb 分发渠道的通用解析。

覆盖三类来源，全部只使用标准库，CLI 通过命令行入口复用同一实现：
- feed:   厂商 JSON 配置接口中取出最新 deb 直链（如 QQ 的 pcConfig.json）
- scrape: 抓取下载页面，用 asset_pattern 从页面链接中筛出目标 deb
- control: 对 deb 发起 Range 部分下载，只取 control 段读取
  Package/Version/Architecture，避免为"检查更新"下载完整安装包。
"""

from __future__ import annotations

import fnmatch
import io
import json
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 部分读取的上限：只需覆盖 ar 头 + control.tar.*，超出说明响应异常。
_CONTROL_HEAD_MAX_BYTES = 8 * 1024 * 1024

_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
_ATTR_URL_RE = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)


class WebSourceError(RuntimeError):
    """官网源解析失败：网络错误、配置取值失败或页面结构不符合预期。"""


def _http_get_text(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, "replace")
    except urllib.error.HTTPError as error:
        raise WebSourceError(f"HTTP {error.code} 请求失败: {url}") from error
    except (urllib.error.URLError, OSError) as error:
        raise WebSourceError(f"网络请求失败: {url} ({error})") from error


def _decompress_zstd(body: bytes) -> bytes | None:
    """用 zstd 命令行工具解压；Python 3.13 的 tarfile 尚不支持 zstd。

    工具缺失或解压失败时返回 None，由调用方回退全量下载。
    """
    executable = shutil.which("zstd")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-dc"], input=body, capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def parse_deb_control_prefix(data: bytes) -> dict[str, str] | None:
    """从 deb 文件的前缀字节里解析 control 段的 Package/Version/Architecture。

    deb 是 ar 归档：魔数后依次是 debian-binary、control.tar.*、data.tar.*。
    只需要第二个成员。数据不完整或压缩格式无法解析时返回 None，
    由调用方决定回退到全量下载。
    """
    if len(data) < 8 or data[:8] != b"!<arch>\n":
        return None
    position = 8
    while position + 60 <= len(data):
        header = data[position : position + 60]
        name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
        try:
            size = int(header[48:58].decode().strip())
        except ValueError:
            return None
        body_start = position + 60
        if name.startswith("control.tar"):
            body = data[body_start : body_start + size]
            if len(body) < size:
                return None
            tar_mode = "r:*"
            if name.endswith(".zst"):
                body = _decompress_zstd(body)
                if body is None:
                    return None
                tar_mode = "r:"
            try:
                with tarfile.open(fileobj=io.BytesIO(body), mode=tar_mode) as archive:
                    # dpkg-deb 打包的成员名是 ./control，
                    # electron-builder 等工具打包的是 control，按去掉前缀后匹配。
                    member = None
                    for entry in archive.getmembers():
                        normalized = entry.name
                        while normalized.startswith("./"):
                            normalized = normalized[2:]
                        if normalized == "control" and entry.isfile():
                            member = archive.extractfile(entry)
                            break
                    if member is None:
                        return None
                    text = member.read().decode("utf-8", "replace")
            except Exception:
                # 任何解析异常都回退全量下载，由 dpkg-deb 做最终裁决。
                return None
            fields: dict[str, str] = {}
            for line in text.splitlines():
                if ": " not in line:
                    continue
                key, value = line.split(": ", 1)
                if key in ("Package", "Version", "Architecture"):
                    fields[key.lower()] = value.strip()
            if all(fields.get(k) for k in ("package", "version", "architecture")):
                return fields
            return None
        position = body_start + size + (size % 2)
    return None


def read_deb_control_head(
    url: str, max_bytes: int = _CONTROL_HEAD_MAX_BYTES
) -> dict[str, str] | None:
    """Range 请求只取 deb 前缀并解析 control 段；失败返回 None 而不抛错。"""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{max_bytes - 1}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read(max_bytes)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return parse_deb_control_prefix(data)


def resolve_feed_url(feed_url: str, path: str) -> str:
    """从 JSON feed 中按点分路径取出下载链接，支持数组下标（如 assets.0.url）。"""
    raw = _http_get_text(feed_url)
    try:
        node = json.loads(raw)
    except json.JSONDecodeError as error:
        raise WebSourceError(f"feed 返回的不是合法 JSON: {feed_url}") from error

    for segment in path.split("."):
        segment = segment.strip()
        if isinstance(node, list):
            if not segment.lstrip("-").isdigit():
                node = None
                break
            index = int(segment)
            node = node[index] if -len(node) <= index < len(node) else None
        elif isinstance(node, dict):
            node = node.get(segment)
        else:
            node = None
        if node is None:
            break

    if not isinstance(node, str) or not node.strip():
        raise WebSourceError(f"feed 中未找到 {path!r} 对应的下载链接: {feed_url}")
    url = node.strip()
    if not url.startswith(("http://", "https://")):
        raise WebSourceError(f"feed 中的下载链接不是 http(s) URL: {url!r}")
    return url


def _match_tokens(url: str) -> list[str]:
    """把 URL 拆成可匹配的文件名片段。

    直接链接按路径段拆分；签名跳转链（如 QQ 音乐的 file_redirect.fcg?...）
    的真实文件名藏在 percent 编码的查询参数里，先解码再按 /?&= 拆分。
    """
    decoded = urllib.parse.unquote(url.replace("&amp;", "&"))
    return [token for token in re.split(r"[/?&=]", decoded) if token]


def _scrape_candidates(html: str, page_url: str) -> list[str]:
    html = html.replace("&amp;", "&")
    urls: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if not candidate.startswith(("http://", "https://")):
            return
        candidate = candidate.rstrip(").,;")
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    # 绝对链接：直出直链（ZCode）与签名跳转链（QQ 音乐）。
    for url in _URL_RE.findall(html):
        add(url)
    # 相对链接：官网页面用相对路径给出 deb（如 Iriun 的 iriunwebcam-x.y.deb）。
    for value in _ATTR_URL_RE.findall(html):
        add(urllib.parse.urljoin(page_url, value.strip()))
    return urls


def resolve_scrape_url(page_url: str, asset_pattern: str) -> str:
    """抓取下载页面，返回唯一匹配 asset_pattern 的链接。

    页面直出直链（ZCode）和签名跳转链（QQ音乐）都能命中；
    匹配到多个不同文件时报错，提示收紧 asset_pattern。
    """
    html = _http_get_text(page_url)
    matches: list[tuple[str, str]] = []
    for url in _scrape_candidates(html, page_url):
        for token in _match_tokens(url):
            if fnmatch.fnmatchcase(token, asset_pattern):
                matches.append((token, url))
                break
    if not matches:
        raise WebSourceError(
            f"在页面中未找到匹配 {asset_pattern!r} 的下载链接: {page_url}"
        )
    distinct = {token for token, _ in matches}
    if len(distinct) > 1:
        listing = "、".join(sorted(distinct))
        raise WebSourceError(
            f"页面匹配到多个文件，请收紧 asset_pattern: {listing}"
        )
    # 同一文件多次出现（如带不同 sign 的链接）时取页面中最后一次。
    return matches[-1][1]


if __name__ == "__main__":
    import sys

    action, *args = sys.argv[1:]
    if action == "control" and len(args) == 1:
        metadata = read_deb_control_head(args[0])
        if not metadata:
            sys.exit(1)
        print(
            "|".join(
                (metadata["package"], metadata["version"], metadata["architecture"])
            )
        )
    elif action == "feed" and len(args) == 2:
        try:
            print(resolve_feed_url(args[0], args[1]))
        except WebSourceError as error:
            print(error, file=sys.stderr)
            sys.exit(1)
    elif action == "scrape" and len(args) == 2:
        try:
            print(resolve_scrape_url(args[0], args[1]))
        except WebSourceError as error:
            print(error, file=sys.stderr)
            sys.exit(1)
    else:
        print(
            "用法: web_source.py control <deb_url>\n"
            "      web_source.py feed <feed_url> <dot.path>\n"
            "      web_source.py scrape <page_url> <asset_pattern>",
            file=sys.stderr,
        )
        sys.exit(2)
