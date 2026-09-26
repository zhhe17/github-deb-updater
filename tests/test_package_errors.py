import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import packages, updates
from app.services.version import VersionError


class PackageErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_and_list_report_query_failure(self):
        pkg = SimpleNamespace(
            name="example",
            display_name="Example",
            repo="test/example",
            asset_pattern="*.deb",
        )
        with (
            patch.object(
                packages,
                "get_installed_version",
                side_effect=VersionError("无法读取本地版本"),
            ),
            patch.object(packages.config, "packages", [pkg]),
            patch.object(
                packages, "resolve_release", new=AsyncMock()
            ) as resolve,
        ):
            checked = await packages.api_check_updates()
            self.assertEqual(checked.total, 1)
            self.assertEqual(checked.errors, 1)
            self.assertEqual(checked.not_installed, 0)
            self.assertIn("无法读取", checked.packages[0].error_message)
            listed = await packages.api_list_packages()
            self.assertEqual(listed["packages"][0]["status"], "error")
            resolve.assert_not_awaited()

    async def test_comparison_failure_is_reported_in_check(self):
        pkg = SimpleNamespace(
            name="example",
            display_name="Example",
            repo="test/example",
            asset_pattern="*.deb",
        )
        with (
            patch.object(packages, "get_installed_version", return_value="1.0"),
            patch.object(
                packages,
                "resolve_release",
                new=AsyncMock(return_value=object()),
            ),
            patch.object(
                packages,
                "get_candidate_package",
                new=AsyncMock(return_value=SimpleNamespace(deb_version="invalid")),
            ),
        ):
            info = await packages._get_package_info(pkg)
            self.assertEqual(info.status, "error")
            self.assertIn("无法比较版本", info.error_message)

    async def test_upgrade_does_not_continue_after_local_query_failure(self):
        pkg = SimpleNamespace(name="example")
        with (
            patch.object(updates.config, "get_package", return_value=pkg),
            patch.object(
                updates,
                "get_installed_version",
                side_effect=VersionError("无法读取本地版本"),
            ),
            patch.object(updates, "install_deb", new=AsyncMock()) as install,
        ):
            result = await updates.api_upgrade_package("example")
            self.assertFalse(result.success)
            self.assertIn("无法读取", result.message)
            install.assert_not_awaited()
