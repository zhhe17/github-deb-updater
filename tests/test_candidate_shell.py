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
MISSING_URL="file://$2/missing.deb"
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
METADATA_HELPER="$SCRIPT_DIR/app/services/metadata_cache.py"
# MISSING_URL 指向不存在的本地文件：部分读确定性地失败（无网络依赖），
# 随后走全量下载（curl shim 复制本地 fixture）。
key=$(python3 "$METADATA_HELPER" key test/repo 42 "$size" first https://github-deb-updater.test/asset)
[[ "$(get_candidate_version cache-test "$MISSING_URL" "$key" "$size")" == 1.0+42 ]]
rm "${CACHE_DIR}/cache-test_${key}.deb"
[[ "$(get_candidate_version cache-test "$MISSING_URL" "$key" "$size")" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 1 ]]
candidate=$(get_candidate_version cache-test "$MISSING_URL" "$key" "$size" install)
[[ "${candidate%%|*}" == 1.0+42 && -f "${candidate#*|}" ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 2 ]]
# 换身份键后元数据未命中；Range 部分读（file:// 直取 control 段）应直接得到版本，不触发下载。
file_key=$(python3 "$METADATA_HELPER" webkey "/local/fixture.deb" "" "" "$size")
[[ "$(get_candidate_version cache-test "file://${FIXTURE_DEB}" "$file_key" "$size")" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 2 ]]
# 部分读结果已写入元数据缓存：再次检查仍无需下载。
[[ "$(get_candidate_version cache-test "file://${FIXTURE_DEB}" "$file_key" "$size")" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 2 ]]
# 部分读与缓存都不可用时回退全量下载。
changed_key=$(python3 "$METADATA_HELPER" key test/repo 42 "$size" changed https://github-deb-updater.test/asset)
[[ "$(get_candidate_version cache-test "$MISSING_URL" "$changed_key" "$size")" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 3 ]]
# 弱身份（键为 nocache）：不做元数据缓存读写，部分读成功时不下载。
[[ "$(get_candidate_version cache-test "file://${FIXTURE_DEB}" nocache "$size")" == 1.0+42 ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 3 ]]
[[ ! -e "${CACHE_DIR}/metadata/nocache.json" ]]
# nocache + 部分读失败：回退全量下载，且每次都是一次性新文件，不复用旧包。
c1=$(get_candidate_version cache-test "$MISSING_URL" nocache "$size" install)
c2=$(get_candidate_version cache-test "$MISSING_URL" nocache "$size" install)
[[ "${c1%%|*}" == 1.0+42 && "${c2%%|*}" == 1.0+42 && -f "${c1#*|}" && -f "${c2#*|}" ]]
[[ "${c1#*|}" != "${c2#*|}" ]]
[[ $(wc -l < "${CACHE_DIR}/downloads.log") -eq 5 ]]
[[ ! -e "${CACHE_DIR}/metadata/nocache.json" ]]
# 资产大小与声明不符时显式失败，不接受不符的安装包。
bad_size_key=$(python3 "$METADATA_HELPER" key test/repo 42 "$((size + 1))" changed https://github-deb-updater.test/asset)
if get_candidate_version cache-test "$MISSING_URL" "$bad_size_key" "$((size + 1))"; then exit 1; fi
"""
            args = ["bash", "-c", script, "test", str(root), str(workspace)]
            result = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                # 失败时附带 xtrace 重跑的输出，便于定位是哪个断言挂了。
                traced = subprocess.run(
                    ["bash", "-x", "-c", script, "test", str(root), str(workspace)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                detail = (result.stdout + result.stderr)[:2000]
                trace = (traced.stdout + traced.stderr)[-4000:]
                self.fail(f"returncode={result.returncode}\n{detail}\n--- xtrace ---\n{trace}")
