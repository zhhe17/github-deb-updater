import subprocess
import unittest
from unittest.mock import patch

from app.services.version import (
    VersionError,
    compare_versions,
    get_installed_version,
    is_update_needed,
    normalize_version,
)


class DebianVersionTests(unittest.TestCase):
    def test_invalid_versions_never_compare_equal(self):
        for version in ("", "invalid", "1 2", "1:bad"):
            with self.subTest(version=version), self.assertRaises(VersionError):
                compare_versions(version, version)
            with self.assertRaises(VersionError):
                is_update_needed(None, version)

    def test_comparison_command_failure_is_not_equality(self):
        with (
            patch("app.services.version.validate_version"),
            patch(
                "app.services.version.subprocess.run",
                return_value=subprocess.CompletedProcess([], 2, stderr="failure"),
            ),
            self.assertRaisesRegex(VersionError, "无法比较版本"),
        ):
            compare_versions("1", "2")

    def test_missing_package_and_removed_package_are_not_installed(self):
        for result in (
            subprocess.CompletedProcess(
                [],
                1,
                stdout="",
                stderr="dpkg-query: no packages found matching missing",
            ),
            subprocess.CompletedProcess([], 0, stdout="rc |1.0", stderr=""),
        ):
            with patch("app.services.version.subprocess.run", return_value=result):
                self.assertIsNone(get_installed_version("missing"))

    def test_query_failures_and_partial_installations_raise(self):
        for result in (
            subprocess.CompletedProcess([], 2, stdout="", stderr="database error"),
            subprocess.CompletedProcess([], 1, stdout="", stderr="unrelated failure"),
            subprocess.CompletedProcess([], 0, stdout="iU |1.0", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="ii |", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="broken", stderr=""),
        ):
            with (
                patch("app.services.version.subprocess.run", return_value=result),
                self.assertRaises(VersionError),
            ):
                get_installed_version("example")
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("dpkg-query", 10)):
            with (
                patch("app.services.version.subprocess.run", side_effect=error),
                self.assertRaises(VersionError),
            ):
                get_installed_version("example")

    def test_normalization_never_discards_debian_version_parts(self):
        for version in ("2:1.2.3-4", "2.1.2+5281", "2.1.2.3", "1.0~beta1"):
            self.assertEqual(normalize_version(version), version)

    def test_compares_epoch_build_revision_four_parts_and_prerelease(self):
        newer_older = [
            ("2:1.0-1", "1:99.0-9"),
            ("2.1.2+5281", "2.1.2+5255"),
            ("1.2.3-2", "1.2.3-1"),
            ("2.1.2.3", "2.1.2.2"),
            ("1.0", "1.0~beta1"),
        ]
        for newer, older in newer_older:
            with self.subTest(newer=newer, older=older):
                self.assertEqual(compare_versions(newer, older), 1)
                self.assertEqual(compare_versions(older, newer), -1)

    def test_piliplus_and_localsend_compare_deb_versions_not_release_tags(self):
        self.assertFalse(is_update_needed("2.1.2+5281", "2.1.2+5281"))
        self.assertFalse(is_update_needed("1.18.2+64", "1.18.2+64"))
        self.assertTrue(is_update_needed("2.1.2+5255", "2.1.2+5281"))

    def test_installed_version_preserves_epoch_and_revision(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout="ii |2:1.2.3+4-5", stderr=""
        )
        with patch("app.services.version.subprocess.run", return_value=completed):
            self.assertEqual(get_installed_version("example"), "2:1.2.3+4-5")


if __name__ == "__main__":
    unittest.main()
