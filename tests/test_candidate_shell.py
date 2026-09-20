"""使用真实 deb 验证 CLI 缓存，不访问网络、不安装软件。"""

import subprocess
import tempfile
import unittest
from pathlib import Path


class ShellCandidateTests(unittest.TestCase):
    def test_metadata_cache_and_install_revalidation(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            control = workspace / "package" / "DEBIAN"
            control.mkdir(parents=True)
            (control / "control").write_text(
                "Package: cache-test\nVersion: 1.0+42\nArchitecture: all\n"
                "Maintainer: Test <test@example.invalid>\nDescription: cache test\n"
            )
            deb = workspace / "fixture.deb"
            subprocess.run(
                ["dpkg-deb", "--build", str(control.parent), str(deb)],
                check=True,
                capture_output=True,
            )
            script = r"""
set -euo pipefail
SCRIPT_DIR="$1"
CACHE_DIR="$2/cache"
FIXTURE_DEB="$2/fixture.deb"
source "$SCRIPT_DIR/lib/version.sh"
source "$SCRIPT_DIR/lib/installer.sh"
log_info() { :; }
log_debug() { :; }
log_warn() { :; }
log_success() { :; }
log_error() { echo "$*" >&2; }
# download_deb 使用的 curl 参数是固定的；复制本地测试 deb 代替网络请求。
curl() {
    printf 'download\n' >> "${CACHE_DIR}/downloads.log"
    cp "$FIXTURE_DEB" "$4"
}
size=$(stat -c %s "$FIXTURE_DEB")
[[ "$(get_candidate_version test/repo cache-test https://example.invalid/asset 42 "$size" first)" == 1.0+42 ]]
key=$(python3 "$SCRIPT_DIR/app/services/metadata_cache.py" key test/repo 42 "$size" first https://example.invalid/asset)
rm "${CACHE_DIR}/cache-test_${key}.deb"
[[ "$(get_candidate_version test/repo cache-test https://example.invalid/asset 42 "$size" first)" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 1 ]]
candidate=$(get_candidate_version test/repo cache-test https://example.invalid/asset 42 "$size" first install)
[[ "${candidate%%|*}" == 1.0+42 && -f "${candidate#*|}" ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 2 ]]
[[ "$(get_candidate_version test/repo cache-test https://example.invalid/asset 42 "$size" changed)" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 3 ]]
# 原资产大小发生变化时，不复用旧元数据，也不接受大小不符的安装包。
if get_candidate_version test/repo cache-test https://example.invalid/asset 42 "$((size + 1))" changed; then exit 1; fi
"""
            result = subprocess.run(
                ["bash", "-c", script, "test", str(root), str(workspace)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
