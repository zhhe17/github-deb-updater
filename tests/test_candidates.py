import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models import ReleaseInfo
from app.services.candidates import (
    CandidateError,
    get_candidate_package,
    release_cache_key,
)


class CandidateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_path = Path(directory.name)
        config_patch = patch(
            "app.services.candidates.config",
            SimpleNamespace(cache_path=self.cache_path),
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # 默认禁用 Range 部分读，让既有用例保持"缓存未命中即全量下载"的语义；
        # 部分读相关用例自行覆盖这个补丁。
        head_patch = patch(
            "app.services.candidates.read_deb_control_head", return_value=None
        )
        head_patch.start()
        self.addCleanup(head_patch.stop)

    async def test_uses_deb_internal_version_instead_of_release_tag(self):
        release = ReleaseInfo(
            asset_id=5281,
            tag_name="2.1.2.3",
            release_version="2.1.2.3",
            asset_name="PiliPlus_2.1.2+5281_amd64.deb",
            download_url="https://example.invalid/piliplus.deb",
        )
        package = SimpleNamespace(name="piliplus", repo="test/piliplus")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.deb"
            path.touch()
            with (
                patch(
                    "app.services.candidates.download_deb",
                    new=AsyncMock(return_value=path),
                ),
                patch(
                    "app.services.candidates.get_system_architecture",
                    return_value="amd64",
                ),
                patch(
                    "app.services.candidates.inspect_deb",
                    return_value={
                        "package": "piliplus",
                        "version": "2.1.2+5281",
                        "architecture": "amd64",
                    },
                ),
            ):
                candidate = await get_candidate_package(package, release)

        self.assertEqual(candidate.deb_version, "2.1.2+5281")
        self.assertEqual(candidate.release.tag_name, "2.1.2.3")

    async def test_rejects_asset_with_wrong_internal_package_name(self):
        release = ReleaseInfo(
            asset_id=1,
            tag_name="v1.0.0",
            release_version="1.0.0",
            asset_name="example.deb",
            download_url="https://example.invalid/example.deb",
        )
        package = SimpleNamespace(name="expected", repo="test/example")
        with (
            patch(
                "app.services.candidates.download_deb",
                new=AsyncMock(return_value=Path("candidate.deb")),
            ),
            patch(
                "app.services.candidates.get_system_architecture", return_value="amd64"
            ),
            patch(
                "app.services.candidates.inspect_deb",
                return_value={
                    "package": "other",
                    "version": "1.0.0",
                    "architecture": "amd64",
                },
            ),
            self.assertRaises(CandidateError),
        ):
            await get_candidate_package(package, release)

    async def test_rejects_asset_for_wrong_architecture(self):
        release = ReleaseInfo(
            asset_id=2,
            tag_name="v1.0.0",
            release_version="1.0.0",
            asset_name="example.deb",
            download_url="https://example.invalid/example.deb",
        )
        package = SimpleNamespace(name="example", repo="test/example")
        with (
            patch(
                "app.services.candidates.download_deb",
                new=AsyncMock(return_value=Path("candidate.deb")),
            ),
            patch(
                "app.services.candidates.get_system_architecture", return_value="amd64"
            ),
            patch(
                "app.services.candidates.inspect_deb",
                return_value={
                    "package": "example",
                    "version": "1.0.0",
                    "architecture": "arm64",
                },
            ),
            self.assertRaisesRegex(CandidateError, "deb 架构为 arm64"),
        ):
            await get_candidate_package(package, release)

    async def test_cache_survives_deb_removal_but_install_requires_file(self):
        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            asset_id=42,
            tag_name="v1",
            release_version="1",
            asset_name="example.deb",
            download_url="https://example.invalid/42",
        )
        path = self.cache_path / "example.deb"
        path.touch()
        with (
            patch(
                "app.services.candidates.download_deb", new=AsyncMock(return_value=path)
            ) as download,
            patch(
                "app.services.candidates.inspect_deb",
                return_value={
                    "package": "example",
                    "version": "1.0+42",
                    "architecture": "amd64",
                },
            ) as inspect,
            patch(
                "app.services.candidates.get_system_architecture", return_value="amd64"
            ),
        ):
            await get_candidate_package(package, release, require_file=False)
            path.unlink()
            cached = await get_candidate_package(package, release, require_file=False)
            self.assertEqual(cached.deb_version, "1.0+42")
            self.assertEqual(cached.path, "")
            self.assertEqual(download.await_count, 1)
            self.assertEqual(inspect.call_count, 1)
            download.return_value = None
            with self.assertRaises(CandidateError):
                await get_candidate_package(package, release)
            self.assertEqual(download.await_count, 2)

    async def test_asset_changes_and_corrupt_cache_force_reinspection(self):
        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            asset_id=42,
            tag_name="v1",
            release_version="1",
            asset_name="example.deb",
            download_url="https://example.invalid/42",
        )
        path = self.cache_path / "example.deb"
        path.touch()
        with (
            patch(
                "app.services.candidates.download_deb", new=AsyncMock(return_value=path)
            ) as download,
            patch(
                "app.services.candidates.inspect_deb",
                return_value={
                    "package": "example",
                    "version": "1.0",
                    "architecture": "amd64",
                },
            ),
            patch(
                "app.services.candidates.get_system_architecture", return_value="amd64"
            ),
        ):
            await get_candidate_package(package, release, require_file=False)
            for change in (
                {"asset_id": 43},
                {"asset_updated_at": "2026-09-05"},
                {"download_url": "https://example.invalid/replacement"},
            ):
                await get_candidate_package(
                    package, release.model_copy(update=change), require_file=False
                )
            await get_candidate_package(
                SimpleNamespace(name="example", repo="other/example"),
                release,
                require_file=False,
            )
            self.assertEqual(download.await_count, 5)
            for record in (self.cache_path / "metadata").glob("*.json"):
                record.write_text("{broken")
            await get_candidate_package(package, release, require_file=False)
            self.assertEqual(download.await_count, 6)

    async def test_size_change_invalidates_cache_and_rejects_wrong_file_size(self):
        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            asset_id=42,
            tag_name="v1",
            release_version="1",
            asset_name="example.deb",
            download_url="https://example.invalid/42",
        )
        path = self.cache_path / "example.deb"
        path.touch()
        with (
            patch(
                "app.services.candidates.download_deb", new=AsyncMock(return_value=path)
            ) as download,
            patch(
                "app.services.candidates.inspect_deb",
                return_value={
                    "package": "example",
                    "version": "1.0",
                    "architecture": "amd64",
                },
            ),
            patch(
                "app.services.candidates.get_system_architecture", return_value="amd64"
            ),
        ):
            await get_candidate_package(package, release, require_file=False)
            with self.assertRaisesRegex(CandidateError, "文件大小不符"):
                await get_candidate_package(
                    package,
                    release.model_copy(update={"asset_size": 123}),
                    require_file=False,
                )
            self.assertEqual(download.await_count, 2)


    async def test_partial_read_serves_check_without_download(self):
        """官网源缓存未命中时，Range 部分读即可完成检查，不触发全量下载。"""
        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            source="url",
            tag_name="example_1.0_amd64.deb",
            asset_name="example_1.0_amd64.deb",
            download_url="https://example.invalid/latest.deb",
            identity_path="/latest.deb",
            asset_size=100,
            etag='"abc"',
            asset_updated_at="Mon, 21 Sep 2026 00:00:00 GMT",
        )
        head = {"package": "example", "version": "1.0", "architecture": "amd64"}
        with (
            patch(
                "app.services.candidates.read_deb_control_head",
                return_value=head,
            ) as head_read,
            patch(
                "app.services.candidates.download_deb",
                new=AsyncMock(return_value=Path("unused.deb")),
            ) as download,
            patch(
                "app.services.candidates.get_system_architecture",
                return_value="amd64",
            ),
        ):
            candidate = await get_candidate_package(package, release, require_file=False)

        self.assertEqual(candidate.deb_version, "1.0")
        self.assertEqual(candidate.path, "")
        download.assert_not_awaited()
        head_read.assert_called_once_with("https://example.invalid/latest.deb")

        # 部分读结果已写入元数据缓存，第二次检查不再发起任何网络请求。
        with (
            patch(
                "app.services.candidates.read_deb_control_head",
            ) as head_read_again,
            patch(
                "app.services.candidates.download_deb",
                new=AsyncMock(return_value=Path("unused.deb")),
            ) as download_again,
        ):
            cached = await get_candidate_package(package, release, require_file=False)
        self.assertEqual(cached.deb_version, "1.0")
        head_read_again.assert_not_called()
        download_again.assert_not_awaited()

    async def test_partial_read_mismatch_falls_back_to_full_download(self):
        """部分读到与配置不符的内容（CDN 新旧构建不一致）时回退全量下载复核，
        全量下载同样不符才报错。"""
        package = SimpleNamespace(name="piliplus", repo="test/piliplus")
        release = ReleaseInfo(
            source="github",
            asset_id=1,
            tag_name="2.1.5",
            release_version="2.1.5",
            asset_name="PiliPlus_linux_2.1.5_amd64.deb",
            download_url="https://example.invalid/piliplus.deb",
        )
        stale_head = {"package": "PiliPlus", "version": "2.1.5+5410", "architecture": "amd64"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.deb"
            path.touch()
            with (
                patch(
                    "app.services.candidates.read_deb_control_head",
                    return_value=stale_head,
                ),
                patch(
                    "app.services.candidates.download_deb",
                    new=AsyncMock(return_value=path),
                ) as download,
                patch(
                    "app.services.candidates.inspect_deb",
                    return_value={
                        "package": "piliplus",
                        "version": "2.1.5+5410",
                        "architecture": "amd64",
                    },
                ),
                patch(
                    "app.services.candidates.get_system_architecture",
                    return_value="amd64",
                ),
            ):
                candidate = await get_candidate_package(package, release, require_file=False)

        # 最终以全量下载复核的结果为准，缓存里是复核后的正确元数据。
        self.assertEqual(candidate.package_name, "piliplus")
        self.assertEqual(candidate.deb_version, "2.1.5+5410")
        download.assert_awaited_once()
        from app.services.metadata_cache import read_metadata
        from app.services.candidates import release_cache_key

        self.assertEqual(
            read_metadata(self.cache_path, release_cache_key(package, release)),
            {
                "package": "piliplus",
                "version": "2.1.5+5410",
                "architecture": "amd64",
            },
        )

    async def test_partial_read_mismatch_raises_when_full_download_also_mismatches(self):
        package = SimpleNamespace(name="piliplus", repo="test/piliplus")
        release = ReleaseInfo(
            source="github",
            asset_id=1,
            tag_name="2.1.5",
            release_version="2.1.5",
            asset_name="PiliPlus_linux_2.1.5_amd64.deb",
            download_url="https://example.invalid/piliplus.deb",
        )
        stale_head = {"package": "PiliPlus", "version": "2.1.5+5410", "architecture": "amd64"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.deb"
            path.touch()
            with (
                patch(
                    "app.services.candidates.read_deb_control_head",
                    return_value=stale_head,
                ),
                patch(
                    "app.services.candidates.download_deb",
                    new=AsyncMock(return_value=path),
                ),
                patch(
                    "app.services.candidates.inspect_deb",
                    return_value={
                        "package": "PiliPlus",
                        "version": "2.1.5+5410",
                        "architecture": "amd64",
                    },
                ),
                patch(
                    "app.services.candidates.get_system_architecture",
                    return_value="amd64",
                ),
                self.assertRaisesRegex(CandidateError, "包名为 PiliPlus"),
            ):
                await get_candidate_package(package, release, require_file=False)

    async def test_web_identity_key_tracks_server_identity_headers(self):
        """同一身份头的重复解析命中同一缓存键；ETag 变化则换新键。"""
        from app.services.metadata_cache import read_metadata

        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            source="url",
            download_url="https://example.invalid/latest.deb",
            identity_path="/latest.deb",
            asset_size=100,
            etag='"v1"',
            asset_updated_at="Mon, 21 Sep 2026 00:00:00 GMT",
        )
        head = {"package": "example", "version": "1.0", "architecture": "amd64"}
        with (
            patch(
                "app.services.candidates.read_deb_control_head", return_value=head
            ),
            patch(
                "app.services.candidates.get_system_architecture",
                return_value="amd64",
            ),
        ):
            await get_candidate_package(package, release, require_file=False)
            key = release_cache_key(package, release)
            self.assertIsNotNone(read_metadata(self.cache_path, key))

            changed = release.model_copy(update={"etag": '"v2"'})
            changed_key = release_cache_key(package, changed)
            self.assertNotEqual(key, changed_key)
            self.assertIsNone(read_metadata(self.cache_path, changed_key))

    async def test_weak_identity_source_bypasses_metadata_cache(self):
        """来源不返回任何身份头（ETag/时间/大小全空）时缓存键退化为纯路径哈希，
        必须绕过元数据缓存：每次检查都重新实测，不写入也不命中。"""
        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            source="url",
            tag_name="example_latest.deb",
            asset_name="example_latest.deb",
            download_url="https://example.invalid/latest.deb",
            identity_path="/latest.deb",
        )
        head = {"package": "example", "version": "1.0", "architecture": "amd64"}
        with (
            patch(
                "app.services.candidates.read_deb_control_head", return_value=head
            ) as head_read,
            patch(
                "app.services.candidates.download_deb",
                new=AsyncMock(return_value=Path("unused.deb")),
            ) as download,
            patch(
                "app.services.candidates.get_system_architecture",
                return_value="amd64",
            ),
        ):
            first = await get_candidate_package(package, release, require_file=False)
            second = await get_candidate_package(package, release, require_file=False)

        self.assertEqual(first.deb_version, "1.0")
        self.assertEqual(second.deb_version, "1.0")
        # 若命中元数据缓存，第二次检查不会再部分读取。
        self.assertEqual(head_read.call_count, 2)
        download.assert_not_awaited()
        metadata_dir = self.cache_path / "metadata"
        self.assertFalse(
            metadata_dir.exists() and any(metadata_dir.iterdir())
        )

    async def test_github_identity_key_matches_legacy_asset_key(self):
        from app.services.metadata_cache import asset_key

        package = SimpleNamespace(name="example", repo="test/example")
        release = ReleaseInfo(
            asset_id=42,
            tag_name="v1",
            release_version="1",
            asset_name="example.deb",
            download_url="https://example.invalid/42",
            asset_size=10,
            asset_updated_at="2026-09-01",
        )
        self.assertEqual(
            release_cache_key(package, release),
            asset_key("test/example", 42, 10, "2026-09-01", "https://example.invalid/42"),
        )


if __name__ == "__main__":
    unittest.main()
