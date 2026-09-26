"""web_source：ar/control 前缀解析、feed 取值路径、页面抓取匹配。"""

import gzip
import io
import tarfile
import unittest
from unittest.mock import patch

from app.services.web_source import (
    WebSourceError,
    parse_deb_control_prefix,
    resolve_feed_url,
    resolve_scrape_url,
)


def _ar_member(name: str, body: bytes) -> bytes:
    header = (
        name.ljust(16).encode()
        + b"0".ljust(12)
        + b"0".ljust(6)
        + b"0".ljust(6)
        + b"644".ljust(8)
        + str(len(body)).ljust(10).encode()
        + b"`\n"
    )
    padding = b"\n" if len(body) % 2 else b""
    return header + body + padding


def build_deb_prefix(
    control_text: str,
    compression: str = "gz",
    truncate: int = 0,
    member_name: str = "./control",
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=f"w:{compression}") as archive:
        data = control_text.encode()
        info = tarfile.TarInfo(member_name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    control_member = buffer.getvalue()

    prefix = b"!<arch>\n"
    prefix += _ar_member("debian-binary", b"2.0\n")
    prefix += _ar_member(f"control.tar.{compression}", control_member)
    return prefix[:truncate] if truncate else prefix


class ParseDebControlPrefixTests(unittest.TestCase):
    CONTROL = (
        "Package: example\nVersion: 1.0+test\nArchitecture: amd64\n"
        "Maintainer: Test <test@example.invalid>\n"
    )

    def test_parses_gzip_control_member(self):
        fields = parse_deb_control_prefix(build_deb_prefix(self.CONTROL, "gz"))
        self.assertEqual(
            fields,
            {"package": "example", "version": "1.0+test", "architecture": "amd64"},
        )

    def test_parses_xz_control_member(self):
        fields = parse_deb_control_prefix(build_deb_prefix(self.CONTROL, "xz"))
        self.assertEqual(fields["version"], "1.0+test")

    def test_parses_control_member_without_dot_slash_prefix(self):
        # electron-builder 打包的 deb 成员名是 control 而非 ./control。
        fields = parse_deb_control_prefix(
            build_deb_prefix(self.CONTROL, "gz", member_name="control")
        )
        self.assertEqual(fields["package"], "example")

    def test_truncated_control_member_returns_none(self):
        prefix = build_deb_prefix(self.CONTROL, "gz")
        self.assertIsNone(parse_deb_control_prefix(prefix[: len(prefix) - 32]))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_deb_control_prefix(b"not an ar archive at all"))
        self.assertIsNone(parse_deb_control_prefix(b""))


SAMPLE_PAGE = """
<a href="https://cdn.example.com/app/releases/1.2.3/app-1.2.3_linux-x64.deb">下载</a>
<a href="https://cdn.example.com/app/releases/1.2.3/app-1.2.3_linux-arm64.deb">ARM</a>
<img src="https://cdn.example.com/app/releases/1.2.3/app-1.2.3_linux-x64.deb.sig">
<script>
var redirect = "https://c.example.com/cgi-bin/file_redirect.fcg?bid=dldir&file=ecosfile%2Fmusic%2Fqqmusic_1.1.8_amd64.deb&sign=1-abc";
</script>
"""


class ScrapeTests(unittest.TestCase):
    def _resolve(self, pattern, page=SAMPLE_PAGE):
        with patch(
            "app.services.web_source._http_get_text", return_value=page
        ) as fetch:
            url = resolve_scrape_url("https://www.example.com/download", pattern)
        fetch.assert_called_once_with("https://www.example.com/download")
        return url

    def test_matches_direct_link_by_filename_token(self):
        self.assertEqual(
            self._resolve("app-*_linux-x64.deb"),
            "https://cdn.example.com/app/releases/1.2.3/app-1.2.3_linux-x64.deb",
        )

    def test_matches_filename_inside_signed_redirect(self):
        self.assertEqual(
            self._resolve("qqmusic_*_amd64.deb"),
            "https://c.example.com/cgi-bin/file_redirect.fcg?bid=dldir"
            "&file=ecosfile%2Fmusic%2Fqqmusic_1.1.8_amd64.deb&sign=1-abc",
        )

    def test_multiple_distinct_matches_are_rejected(self):
        with self.assertRaisesRegex(WebSourceError, "收紧 asset_pattern"):
            self._resolve("*.deb")

    def test_matches_relative_link_resolved_against_page(self):
        page = '<a href="iriunwebcam-2.9.3.deb">下载</a><img src="/logo.svg">'
        with patch(
            "app.services.web_source._http_get_text", return_value=page
        ):
            url = resolve_scrape_url("https://iriun.com", "iriunwebcam-*.deb")
        self.assertEqual(url, "https://iriun.com/iriunwebcam-2.9.3.deb")

    def test_no_match_is_explicit_error(self):
        with self.assertRaisesRegex(WebSourceError, "未找到匹配"):
            self._resolve("nomatch-*_amd64.deb")


class FeedTests(unittest.TestCase):
    CONFIG = """
    {"Linux": {"version": "3.2.34", "x64DownloadUrl": {"deb": "https://qqdl.example.com/QQ_3.2.34_amd64.deb"}}}
    """

    def _resolve(self, path, payload=CONFIG):
        with patch(
            "app.services.web_source._http_get_text", return_value=payload
        ):
            return resolve_feed_url("https://config.example.com/pcConfig.json", path)

    def test_resolves_dot_path(self):
        self.assertEqual(
            self._resolve("Linux.x64DownloadUrl.deb"),
            "https://qqdl.example.com/QQ_3.2.34_amd64.deb",
        )

    def test_supports_array_index(self):
        payload = '{"assets": [{"url": "https://x.example.com/a.deb"}]}'
        self.assertEqual(self._resolve("assets.0.url", payload), "https://x.example.com/a.deb")

    def test_missing_path_is_explicit_error(self):
        with self.assertRaisesRegex(WebSourceError, "未找到"):
            self._resolve("Linux.armDownloadUrl.deb")

    def test_non_http_value_is_rejected(self):
        payload = '{"Linux": {"x64DownloadUrl": {"deb": "ftp://x/y.deb"}}}'
        with self.assertRaisesRegex(WebSourceError, "http"):
            self._resolve("Linux.x64DownloadUrl.deb", payload)

    def test_invalid_json_is_explicit_error(self):
        with self.assertRaisesRegex(WebSourceError, "合法 JSON"):
            self._resolve("a.b", "not json")


if __name__ == "__main__":
    unittest.main()
