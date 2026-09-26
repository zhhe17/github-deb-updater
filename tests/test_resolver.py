"""resolver：来源分派、配置校验、签名钩子、下载地址探测。"""

import unittest
from unittest.mock import patch

import httpx

from app.config import PackageConfig
from app.services.resolver import (
    ResolverError,
    _probe,
    label_from_url,
    resolve_release,
    run_sign_command,
)


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _client_patch(handler):
    """让 resolver 的探测请求走 MockTransport（先保存真实类，避免递归引用）。"""
    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        kwargs.pop("proxy", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    return patch("app.services.resolver.httpx.AsyncClient", side_effect=factory)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "redirect.example":
        return httpx.Response(
            302,
            headers={"Location": "https://files.example.com/v/1.0/app-1.0_amd64.deb"},
        )
    return httpx.Response(
        200,
        headers={
            "Content-Length": "12345",
            "ETag": '"deadbeef"',
            "Last-Modified": "Mon, 21 Sep 2026 00:00:00 GMT",
        },
    )


class LabelTests(unittest.TestCase):
    def test_extracts_filename_ignoring_query(self):
        self.assertEqual(
            label_from_url("https://cdn.example.com/a/b/app-1.2.deb?sign=1-x"),
            "app-1.2.deb",
        )

    def test_falls_back_to_host(self):
        self.assertEqual(label_from_url("https://cdn.example.com"), "cdn.example.com")


class ValidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_github_source_requires_repo(self):
        pkg = PackageConfig(name="example", source="github")
        with self.assertRaisesRegex(ResolverError, "repo"):
            await resolve_release(pkg)

    async def test_url_source_requires_url(self):
        pkg = PackageConfig(name="example", source="url")
        with self.assertRaisesRegex(ResolverError, "url"):
            await resolve_release(pkg)

    async def test_feed_source_requires_url_and_path(self):
        pkg = PackageConfig(name="example", source="feed", feed_url="https://x/c.json")
        with self.assertRaisesRegex(ResolverError, "feed_path"):
            await resolve_release(pkg)

    async def test_scrape_source_requires_page_and_pattern(self):
        pkg = PackageConfig(name="example", source="scrape")
        with self.assertRaisesRegex(ResolverError, "page_url"):
            await resolve_release(pkg)

    async def test_unknown_source_is_rejected(self):
        pkg = PackageConfig(name="example", source="ftp")
        with self.assertRaisesRegex(ResolverError, "未知的来源类型"):
            await resolve_release(pkg)


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_collects_identity_headers_and_final_path(self):
        pkg = PackageConfig(name="example", source="url")
        with _client_patch(_ok_handler):
            release = await _probe(pkg, "https://redirect.example/latest", "url")

        self.assertEqual(release.source, "url")
        self.assertEqual(release.download_url, "https://redirect.example/latest")
        self.assertEqual(release.tag_name, "app-1.0_amd64.deb")
        self.assertEqual(release.identity_path, "/v/1.0/app-1.0_amd64.deb")
        self.assertEqual(release.asset_size, 12345)
        self.assertEqual(release.etag, '"deadbeef"')
        self.assertEqual(release.asset_updated_at, "Mon, 21 Sep 2026 00:00:00 GMT")

    async def test_probe_falls_back_to_get_on_405(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(200, headers={"Content-Length": "7"})

        pkg = PackageConfig(name="example", source="url")
        with _client_patch(handler):
            release = await _probe(pkg, "https://files.example.com/a.deb", "url")
        self.assertEqual(release.asset_size, 7)

    async def test_probe_error_status_is_explicit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        pkg = PackageConfig(name="example", source="url")
        with _client_patch(handler):
            with self.assertRaisesRegex(ResolverError, "HTTP 403"):
                await _probe(pkg, "https://files.example.com/a.deb", "url")

    async def test_probe_network_error_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        pkg = PackageConfig(name="example", source="url")
        with _client_patch(handler):
            with self.assertRaisesRegex(ResolverError, "探测下载地址失败"):
                await _probe(pkg, "https://files.example.com/a.deb", "url")


class UrlSourceEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_source_resolves_through_probe(self):
        pkg = PackageConfig(
            name="example",
            source="url",
            url="https://redirect.example/latest",
        )
        with _client_patch(_ok_handler):
            release = await resolve_release(pkg)
        self.assertEqual(release.source, "url")
        self.assertEqual(release.tag_name, "app-1.0_amd64.deb")


class SignCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_passes_url_via_environment(self):
        signed = run_sign_command('printf %s "$SIGN_URL"', "https://raw.example/a.deb")
        self.assertEqual(signed, "https://raw.example/a.deb")

    def test_failure_is_explicit(self):
        with self.assertRaisesRegex(ResolverError, "签名命令"):
            run_sign_command("exit 3", "https://raw.example/a.deb")

    def test_non_url_output_is_rejected(self):
        with self.assertRaisesRegex(ResolverError, "签名命令"):
            run_sign_command("echo hello", "https://raw.example/a.deb")


if __name__ == "__main__":
    unittest.main()
