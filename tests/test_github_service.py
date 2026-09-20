import unittest

from app.services.github import GitHubService


class CompatibleReleaseTests(unittest.TestCase):
    def test_release_info_keeps_tag_separate_from_deb_version(self):
        releases = [
            {
                "tag_name": "2.1.2.3",
                "assets": [
                    {
                        "id": 5281,
                        "name": "PiliPlus_2.1.2+5281_amd64.deb",
                        "browser_download_url": "https://example.invalid/piliplus.deb",
                        "size": 123,
                    }
                ],
            }
        ]

        result = GitHubService._find_release_info(releases, "PiliPlus_*_amd64.deb")

        self.assertIsNotNone(result)
        self.assertEqual(result.tag_name, "2.1.2.3")
        self.assertEqual(result.release_version, "2.1.2.3")
        self.assertEqual(result.asset_id, 5281)

    def test_uses_newest_stable_release_containing_matching_asset(self):
        releases = [
            {
                "tag_name": "v1.18.1",
                "assets": [
                    {
                        "name": "LocalSend-1.18.1-android-x64.apk",
                        "browser_download_url": "https://example.invalid/mobile.apk",
                    }
                ],
            },
            {
                "tag_name": "v1.18.0",
                "assets": [
                    {
                        "name": "LocalSend-1.18.0-linux-x86-64.deb",
                        "browser_download_url": "https://example.invalid/localsend.deb",
                    }
                ],
            },
        ]

        result = GitHubService._find_compatible_release(
            releases, "LocalSend-*-linux-x86-64.deb"
        )

        self.assertEqual(result, ("1.18.0", "https://example.invalid/localsend.deb"))

    def test_skips_prereleases_and_preserves_prefixed_tag_support(self):
        releases = [
            {
                "tag_name": "desktop-v2.0.0-beta",
                "prerelease": True,
                "assets": [
                    {
                        "name": "app_2.0.0_amd64.deb",
                        "browser_download_url": "https://example.invalid/beta.deb",
                    }
                ],
            },
            {
                "tag_name": "desktop-v1.9.0",
                "assets": [
                    {
                        "name": "app_1.9.0_amd64.deb",
                        "browser_download_url": "https://example.invalid/stable.deb",
                    }
                ],
            },
        ]

        result = GitHubService._find_compatible_release(releases, "app_*_amd64.deb")

        self.assertEqual(result, ("1.9.0", "https://example.invalid/stable.deb"))


if __name__ == "__main__":
    unittest.main()
