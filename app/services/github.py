"""GitHub API 交互服务"""

import asyncio
import os
from typing import Optional

import httpx

from app.config import config

GITHUB_API_BASE = "https://api.github.com"


class GitHubService:
    """GitHub API 服务"""

    def __init__(self):
        self.token = config.app_config.github_token
        self._client: Optional[httpx.AsyncClient] = None

    def _get_proxy_url(self) -> Optional[str]:
        """获取代理 URL，优先使用 HTTPS_PROXY/HTTP_PROXY，避免 ALL_PROXY 中的 SOCKS 协议"""
        # 优先使用 HTTP/HTTPS 代理（httpx 原生支持）
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not proxy:
            proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        # 只接受 http/https 协议的代理，过滤掉 socks 等不支持的协议
        if proxy and proxy.startswith("http"):
            return proxy
        return None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            proxy_url = self._get_proxy_url()
            print(f"[GitHub] 使用代理: {proxy_url or '(无)'}")

            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                proxy=proxy_url,
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self, url: str, max_retries: int = 3
    ) -> Optional[dict]:
        """带重试的 API 请求"""
        client = await self._get_client()

        for attempt in range(max_retries):
            try:
                response = await client.get(url)

                if response.status_code == 200:
                    return response.json()

                if response.status_code in (403, 429):
                    # 速率限制，等待后重试
                    wait = (attempt + 1) * 5
                    print(f"[GitHub] 速率限制 {response.status_code}，等待 {wait}s 后重试: {url}")
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 404:
                    return None

                # 其他错误，等待后重试
                print(f"[GitHub] HTTP {response.status_code}，第 {attempt+1} 次尝试: {url}")
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)
                    continue

                return None

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                print(f"[GitHub] 网络错误 (第 {attempt+1} 次): {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)
                    continue
                return None

        return None

    async def get_latest_release(self, repo: str) -> Optional[dict]:
        """获取最新 Release 信息

        Returns:
            dict: {"tag_name": "v1.0.0", "assets": [{"name": "file.deb", "url": "..."}]}
        """
        url = f"{GITHUB_API_BASE}/repos/{repo}/releases/latest"
        data = await self._request_with_retry(url)

        if not data:
            return None

        tag_name = data.get("tag_name", "")
        assets = []

        for asset in data.get("assets", []):
            assets.append({
                "name": asset.get("name", ""),
                "url": asset.get("browser_download_url", ""),
                "size": asset.get("size", 0),
            })

        return {
            "tag_name": tag_name,
            "assets": assets,
        }

    async def get_asset_url(self, repo: str, asset_pattern: str) -> Optional[str]:
        """获取匹配模式的资产下载 URL

        Args:
            repo: GitHub 仓库 (owner/repo)
            asset_pattern: 资产文件名模式（支持通配符）

        Returns:
            str: 下载 URL，未找到返回 None
        """
        release = await self.get_latest_release(repo)
        if not release:
            return None

        import fnmatch

        for asset in release["assets"]:
            if fnmatch.fnmatch(asset["name"], asset_pattern):
                return asset["url"]

        return None

    async def get_version_and_url(
        self, repo: str, asset_pattern: str
    ) -> tuple[Optional[str], Optional[str]]:
        """同时获取版本号和下载 URL

        Returns:
            tuple: (version, download_url)
        """
        release = await self.get_latest_release(repo)
        if not release:
            return None, None

        # 从 tag_name 提取版本号（去掉常见前缀如 v、desktop-v 等）
        tag = release["tag_name"]
        version = tag
        # 去除最后一个 '-' 之前的所有前缀（如 desktop-v1.6.0 -> 1.6.0）
        # 先尝试去掉 'v' 前缀
        if version.startswith("v") and not version.startswith("v-"):
            version = version[1:]
        # 如果仍包含 '-' 且不是纯版本号，去掉前缀部分
        elif "-" in version:
            parts = version.split("-")
            last = parts[-1]
            # 如果最后一段以数字开头，视为版本号
            # 也可能最后一段是 v1.6.0 这种格式，再去掉 v 前缀
            if last and (last[0].isdigit() or (last.startswith("v") and len(last) > 1 and last[1].isdigit())):
                version = last[1:] if last.startswith("v") else last

        # 查找匹配的资产
        import fnmatch

        download_url = None
        for asset in release["assets"]:
            if fnmatch.fnmatch(asset["name"], asset_pattern):
                download_url = asset["url"]
                break

        return version, download_url


# 全局服务实例
github_service = GitHubService()
