import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models import ReleaseInfo
from app.services.candidates import CandidateError, get_candidate_package


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


if __name__ == "__main__":
    unittest.main()
