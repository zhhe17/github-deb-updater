"""来源解析层：把不同分发渠道解析成统一的 deb 资产指针（ReleaseInfo）。

管线中只有这一步与来源有关；下载校验、dpkg 版本比较、安装对来源无感知。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from urllib.parse import unquote, urlsplit

import httpx

from app.config import config
from app.models import ReleaseInfo
from app.services.github import github_service
from app.services.installer import _get_proxy_url
from app.services.web_source import WebSourceError, resolve_feed_url, resolve_scrape_url

VALID_SOURCES = ("github", "url", "feed", "scrape")

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class ResolverError(RuntimeError):
    """来源解析失败：配置缺失、网络错误或页面结构不符合预期。"""


def normalize_source(pkg) -> str:
    source = (getattr(pkg, "source", "") or "github").strip().lower()
    if source not in VALID_SOURCES:
        raise ResolverError(
            f"未知的来源类型 {source!r}（可选: {', '.join(VALID_SOURCES)}）"
        )
    return source


def validate_package_source(pkg) -> None:
    """按来源类型校验必填配置，给出可读的错误信息。"""
    source = normalize_source(pkg)
    if source == "github" and not getattr(pkg, "repo", ""):
        raise ResolverError("github 来源必须配置 repo（owner/repo）")
    if source == "url" and not getattr(pkg, "url", ""):
        raise ResolverError("url 来源必须配置 url（指向最新 deb 的固定链接）")
    if source == "feed" and (
        not getattr(pkg, "feed_url", "") or not getattr(pkg, "feed_path", "")
    ):
        raise ResolverError("feed 来源必须配置 feed_url 和 feed_path")
    if source == "scrape" and (
        not getattr(pkg, "page_url", "") or not getattr(pkg, "asset_pattern", "")
    ):
        raise ResolverError("scrape 来源必须配置 page_url 和 asset_pattern")


def label_from_url(url: str) -> str:
    """取 URL 里的文件名作为展示标签。"""
    path = urlsplit(url).path.rstrip("/")
    name = unquote(path.rsplit("/", 1)[-1]) if path else ""
    return name or (urlsplit(url).netloc or url)


async def resolve_release(pkg) -> ReleaseInfo:
    """解析出一个确定的 deb 资产；失败抛 ResolverError，不静默降级。"""
    source = normalize_source(pkg)
    validate_package_source(pkg)

    if source == "github":
        release = await github_service.get_release_info(pkg.repo, pkg.asset_pattern)
        if release is None:
            raise ResolverError(
                f"无法获取 {pkg.repo} 中匹配 {pkg.asset_pattern} 的正式 Release 资产"
            )
        return release

    try:
        if source == "url":
            raw_url = pkg.url
        elif source == "feed":
            raw_url = await asyncio.to_thread(
                resolve_feed_url, pkg.feed_url, pkg.feed_path
            )
        else:  # scrape
            raw_url = await asyncio.to_thread(
                resolve_scrape_url, pkg.page_url, pkg.asset_pattern
            )
    except WebSourceError as error:
        raise ResolverError(str(error)) from error

    if getattr(pkg, "sign_command", ""):
        raw_url = await asyncio.to_thread(run_sign_command, pkg.sign_command, raw_url)

    return await _probe(pkg, raw_url, source)


def run_sign_command(command: str, url: str) -> str:
    """执行签名钩子：通过环境变量 SIGN_URL 传入原始链接，stdout 返回签名链接。"""
    environment = {**os.environ, "SIGN_URL": url}
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=config.base_dir,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise ResolverError("签名命令执行超时") from error
    signed = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if result.returncode != 0 or not signed.startswith(("http://", "https://")):
        detail = (result.stderr or result.stdout or "").strip()
        raise ResolverError(
            f"签名命令未返回有效链接: {detail or 'stdout 为空'}"
        )
    return signed


async def _probe(pkg, download_url: str, source: str) -> ReleaseInfo:
    """HEAD 探测下载地址：跟随重定向，收集缓存身份所需的响应头。"""
    headers = {"User-Agent": _BROWSER_UA}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            proxy=_get_proxy_url(),
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.head(download_url, headers=headers)
            if response.status_code in (405, 501):
                # 个别站点不接受 HEAD：流式 GET 只取响应头即关闭，
                # 避免非流式请求把整个 deb 读进内存。
                async with client.stream(
                    "GET", download_url, headers=headers
                ) as stream_response:
                    response = stream_response
    except httpx.HTTPError as error:
        raise ResolverError(
            f"探测下载地址失败: {type(error).__name__}: {error}"
        ) from error

    if response.status_code != 200:
        raise ResolverError(
            f"下载地址不可用（HTTP {response.status_code}）: {label_from_url(download_url)}"
        )

    final_url = str(response.url)
    etag = (response.headers.get("ETag") or "").strip()
    last_modified = (response.headers.get("Last-Modified") or "").strip()
    try:
        size = int(response.headers.get("Content-Length") or 0)
    except ValueError:
        size = 0
    asset_name = label_from_url(final_url) or label_from_url(download_url)
    identity_path = urlsplit(final_url).path or urlsplit(download_url).path

    return ReleaseInfo(
        asset_id=0,
        tag_name=asset_name,
        release_version="",
        asset_name=asset_name,
        download_url=download_url,
        asset_size=size,
        asset_updated_at=last_modified or None,
        etag=etag or None,
        source=source,
        identity_path=identity_path,
    )
