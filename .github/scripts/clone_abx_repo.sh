#!/usr/bin/env bash
set -Eeuo pipefail

repo_name="$1"
target_dir="${2:-$repo_name}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lock_file="$repo_root/uv.lock"
tooling_config="$repo_root/.github/configs/ci-tooling.json"

locked_version() {
    local wanted="$1" line package=""
    while IFS= read -r line; do
        case "$line" in
            '[[package]]') package="" ;;
            "name = \"${wanted}\"") package="$wanted" ;;
            'version = "'*'"')
                if [[ "$package" == "$wanted" ]]; then
                    line="${line#version = \"}"
                    printf '%s\n' "${line%\"}"
                    return 0
                fi
                ;;
        esac
    done < "$lock_file"
    return 1
}

version="$(locked_version "$repo_name")"
[[ -n "$version" ]] || { echo "Could not find ${repo_name} in uv.lock" >&2; exit 1; }

abxpkg_version="$(locked_version abxpkg)"
[[ -n "$abxpkg_version" ]] || { echo "Could not find abxpkg in uv.lock" >&2; exit 1; }

ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${RUNNER_TEMP:-/tmp}/archivebox-clone-abxpkg}"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-project --with "abxpkg==$abxpkg_version" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$tooling_config:git_binaries" \
    >/dev/null
git_binary="$ABXPKG_LIB_DIR/env/bin/git"
[[ -L "$git_binary" ]]
[[ -x "$git_binary" ]]

echo "Cloning ArchiveBox/${repo_name}@v${version} into ${target_dir}"
"$git_binary" clone --depth=1 --branch "v${version}" "https://github.com/ArchiveBox/${repo_name}.git" "$target_dir"
