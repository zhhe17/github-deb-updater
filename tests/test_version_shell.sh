#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/lib/version.sh"
source "$ROOT_DIR/lib/logger.sh"
source "$ROOT_DIR/lib/installer.sh"

assert_compare() {
    local first="$1" second="$2" expected="$3" actual
    if version_compare "$first" "$second"; then actual=0; else actual=$?; fi
    [[ "$actual" -eq "$expected" ]] || {
        echo "comparison failed: $first <> $second, expected $expected got $actual" >&2
        exit 1
    }
}

assert_compare "2.1.2+5281" "2.1.2+5255" 1
assert_compare "2.1.2.3" "2.1.2.2" 1
assert_compare "2:1.0-1" "1:99.0-9" 1
assert_compare "1.0~beta1" "1.0" 2
assert_compare "1.18.2+64" "1.18.2+64" 0
assert_compare "invalid" "invalid" 3
assert_compare "" "" 3

if is_update_needed "invalid" "1.0"; then
    exit 1
else
    [[ $? -eq 2 ]]
fi
if is_update_needed "" "invalid"; then
    exit 1
else
    [[ $? -eq 2 ]]
fi

dpkg-query() { echo "database error" >&2; return 2; }
if get_installed_version example; then
    echo "query failure was treated as not installed" >&2
    exit 1
fi
dpkg-query() { echo "dpkg-query: no packages found matching example" >&2; return 1; }
[[ -z "$(get_installed_version example)" ]]
dpkg-query() { printf 'iU |1.0'; }
if get_installed_version example; then exit 1; fi

dpkg-query() {
    printf 'ii |2:1.2.3+4-5'
}
[[ "$(get_installed_version example)" == "2:1.2.3+4-5" ]]

dpkg-deb() {
    case "${*: -1}" in
        Package) printf 'piliplus\n' ;;
        Version) printf '2.1.2+5281\n' ;;
        *) return 1 ;;
    esac
}
[[ "$(get_deb_package_version /tmp/example.deb piliplus)" == "2.1.2+5281" ]]
if get_deb_package_version /tmp/example.deb wrong-package >/dev/null; then
    echo "wrong internal package name was accepted" >&2
    exit 1
fi
