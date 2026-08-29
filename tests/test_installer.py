import subprocess
import unittest
from unittest.mock import patch

from app.services.installer import uninstall_package


class UninstallPackageTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_apt_remove_without_autoremove_when_running_as_root(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch("app.services.installer.os.geteuid", return_value=0), patch(
            "app.services.installer._run_cmd", return_value=completed
        ) as run_cmd:
            result = await uninstall_package("piliplus")

        self.assertTrue(result.success)
        self.assertEqual(result.package_name, "piliplus")
        run_cmd.assert_called_once_with(["apt-get", "remove", "-y", "piliplus"], 180)

    async def test_returns_command_error(self):
        completed = subprocess.CompletedProcess([], 100, stdout="", stderr="package is not installed")

        with patch("app.services.installer.os.geteuid", return_value=0), patch(
            "app.services.installer._run_cmd", return_value=completed
        ):
            result = await uninstall_package("piliplus")

        self.assertFalse(result.success)
        self.assertIn("package is not installed", result.message)


if __name__ == "__main__":
    unittest.main()
