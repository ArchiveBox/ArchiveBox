#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"
MONOREPO_REMOTE="${MONOREPO_REMOTE:-$GITHUB_BASE/monorepo.git}"
REPO_NAMES=(abxbus abxpkg abx-plugins abx-dl archivebox)
GIT_BINARY=""

locked_version() {
    local lock_file="$1" wanted="$2" line package=""
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

resolve_git_binary() {
    local lock_file="$SCRIPT_REPO_ROOT/uv.lock"
    if [[ ! -f "$lock_file" && -f "$SCRIPT_REPO_ROOT/archivebox/uv.lock" ]]; then
        lock_file="$SCRIPT_REPO_ROOT/archivebox/uv.lock"
    fi
    [[ -f "$lock_file" ]] || { printf 'Unable to find an ArchiveBox uv.lock for abxpkg bootstrap\n' >&2; exit 1; }

    local abxpkg_version
    abxpkg_version="$(locked_version "$lock_file" abxpkg)"
    [[ -n "$abxpkg_version" ]] || { printf 'Unable to find abxpkg in %s\n' "$lock_file" >&2; exit 1; }

    export ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/archivebox/setup-monorepo-abxpkg}"
    mkdir -p "$ABXPKG_LIB_DIR/env/bin"
    uv run --no-cache --no-project --with "abxpkg==$abxpkg_version" abxpkg env \
        --install \
        --lib="$ABXPKG_LIB_DIR" \
        --binproviders=env,brew,apt \
        git >/dev/null
    GIT_BINARY="$ABXPKG_LIB_DIR/env/bin/git"
    test -L "$GIT_BINARY"
    test -x "$GIT_BINARY"
}

repo_target_branch() {
    case "$1" in
        archivebox)
            printf 'dev\n'
            ;;
        *)
            printf 'main\n'
            ;;
    esac
}

is_member_repo() {
    local repo_root="$1"
    local repo_name

    for repo_name in "${REPO_NAMES[@]}"; do
        if [[ "$(basename "$repo_root")" == "$repo_name" ]]; then
            return 0
        fi
    done

    return 1
}

monorepo_remote_matches() {
    case "$1" in
        git@github.com:ArchiveBox/monorepo.git | \
        git+ssh://git@github.com/ArchiveBox/monorepo.git | \
        https://github.com/ArchiveBox/monorepo.git)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

bootstrap_build_dependencies() {
    export ABXPKG_LIB_DIR="$ROOT_DIR/.venv/abxpkg"
    mkdir -p "$ABXPKG_LIB_DIR/env/bin"
    export PATH="$ABXPKG_LIB_DIR/env/bin:$PATH"

    case "$OSTYPE" in
        linux*)
            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env,apt \
                --overrides='{"apt":{"install_args":["build-essential"]}}' \
                cc >/dev/null
            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env,apt \
                --overrides='{"env":{"version":["ldapsearch","-VV"]},"apt":{"install_args":["ldap-utils","python3-dev","python3-setuptools","libssl-dev","libldap2-dev","libsasl2-dev","zlib1g-dev","libatomic1"],"version":["ldapsearch","-VV"]}}' \
                ldapsearch >/dev/null

            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env \
                cc >/dev/null
            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env \
                --overrides='{"env":{"version":["ldapsearch","-VV"]}}' \
                ldapsearch >/dev/null

            test -L "$ABXPKG_LIB_DIR/env/bin/cc"
            test -x "$ABXPKG_LIB_DIR/env/bin/cc"
            test -L "$ABXPKG_LIB_DIR/env/bin/ldapsearch"
            test -x "$ABXPKG_LIB_DIR/env/bin/ldapsearch"
            ;;
        darwin*)
            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env \
                brew >/dev/null

            local brew_binary="$ABXPKG_LIB_DIR/env/bin/brew"
            local brew_target
            local brew_root
            brew_target="$(readlink "$brew_binary")"
            test -x "$brew_target"
            brew_root="$(dirname "$(dirname "$brew_target")")"
            export ABXPKG_BREW_ROOT="$brew_root"

            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env,brew \
                --overrides='{"brew":{"install_args":["llvm"]}}' \
                clang >/dev/null
            uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                --install \
                --no-cache \
                --json \
                --lib="$ABXPKG_LIB_DIR" \
                --binproviders=env,brew \
                --overrides='{"env":{"version":["ldapvc","-VV"]},"brew":{"install_args":["openldap"],"postinstall_scripts":true,"version":["ldapvc","-VV"]}}' \
                ldapvc >/dev/null

            PATH="$PATH:$brew_root/opt/llvm/bin" \
                uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                    --install \
                    --no-cache \
                    --json \
                    --lib="$ABXPKG_LIB_DIR" \
                    --binproviders=env \
                    clang >/dev/null
            PATH="$PATH:$brew_root/opt/openldap/bin" \
                uv tool run --from "$ROOT_DIR/abxpkg" abxpkg env \
                    --install \
                    --no-cache \
                    --json \
                    --lib="$ABXPKG_LIB_DIR" \
                    --binproviders=env \
                    --overrides='{"env":{"version":["ldapvc","-VV"]}}' \
                    ldapvc >/dev/null

            test -L "$ABXPKG_LIB_DIR/env/bin/clang"
            test -x "$ABXPKG_LIB_DIR/env/bin/clang"
            test -L "$ABXPKG_LIB_DIR/env/bin/ldapvc"

            local ldapvc_target
            local next_ldapvc_target
            local openldap_prefix
            ldapvc_target="$(readlink "$ABXPKG_LIB_DIR/env/bin/ldapvc")"
            while [[ -L "$ldapvc_target" ]]; do
                next_ldapvc_target="$(readlink "$ldapvc_target")"
                if [[ "$next_ldapvc_target" == /* ]]; then
                    ldapvc_target="$next_ldapvc_target"
                else
                    ldapvc_target="$(dirname "$ldapvc_target")/$next_ldapvc_target"
                fi
            done
            test -x "$ldapvc_target"
            openldap_prefix="$(dirname "$(dirname "$ldapvc_target")")"
            test -f "$openldap_prefix/include/ldap.h"
            test -f "$openldap_prefix/lib/libldap.dylib"
            export CPPFLAGS="-I$openldap_prefix/include${CPPFLAGS:+ $CPPFLAGS}"
            export LDFLAGS="-L$openldap_prefix/lib${LDFLAGS:+ $LDFLAGS}"
            export PKG_CONFIG_PATH="$openldap_prefix/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
            ;;
        *)
            printf 'Unsupported monorepo setup platform: %s\n' "$OSTYPE" >&2
            exit 1
            ;;
    esac
}

sync_workspace() {
    uv sync --all-packages --all-extras --all-groups --no-cache --active
}

ensure_setup_link() {
    local repo_name="$1"
    local repo_dir="$ROOT_DIR/$repo_name"
    local link_path="$repo_dir/bin/setup_monorepo.sh"
    local source_path="$ROOT_DIR/bin/setup.sh"

    mkdir -p "$repo_dir/bin"

    if [[ -e "$link_path" ]] && [[ "$source_path" -ef "$link_path" ]]; then
        return
    fi

    if [[ -d "$link_path" && ! -L "$link_path" ]]; then
        printf 'Refusing to replace directory: %s\n' "$link_path" >&2
        exit 1
    fi

    rm -f "$link_path"
    ln "$source_path" "$link_path"
}

bootstrap_monorepo_root() {
    local monorepo_root="$1"
    local origin_url=""

    if [[ -d "$monorepo_root/.git" ]]; then
        origin_url="$("$GIT_BINARY" -C "$monorepo_root" remote get-url origin 2>/dev/null || true)"

        if [[ -n "$origin_url" ]] && ! monorepo_remote_matches "$origin_url"; then
            printf 'Refusing to reuse existing git repo at %s (origin: %s)\n' "$monorepo_root" "$origin_url" >&2
            exit 1
        fi

        if [[ -z "$origin_url" ]]; then
            "$GIT_BINARY" -C "$monorepo_root" remote add origin "$MONOREPO_REMOTE"
        fi

        printf 'Updating monorepo root: %s\n' "$monorepo_root"
        if "$GIT_BINARY" -C "$monorepo_root" -c pull.rebase=false pull --ff-only --quiet >/dev/null 2>&1; then
            printf 'Updated monorepo root\n'
        else
            printf 'Skipping monorepo pull (local changes, divergent branch, detached HEAD, or no upstream)\n' >&2
        fi
        return
    fi

    printf 'Bootstrapping monorepo root in %s\n' "$monorepo_root"
    "$GIT_BINARY" -C "$monorepo_root" init -b main >/dev/null
    "$GIT_BINARY" -C "$monorepo_root" remote add origin "$MONOREPO_REMOTE"
    "$GIT_BINARY" -C "$monorepo_root" fetch --depth=1 origin main --quiet

    if "$GIT_BINARY" -C "$monorepo_root" checkout -B main --track origin/main >/dev/null 2>&1; then
        printf 'Initialized monorepo root\n'
    else
        printf 'Failed to materialize monorepo root in %s; existing files likely conflict with tracked monorepo files\n' "$monorepo_root" >&2
        exit 1
    fi
}

resolve_git_binary

if is_member_repo "$SCRIPT_REPO_ROOT"; then
    ROOT_DIR="$(cd -- "$SCRIPT_REPO_ROOT/.." && pwd)"
    bootstrap_monorepo_root "$ROOT_DIR"
elif [[ -f "$SCRIPT_REPO_ROOT/pyproject.toml" ]]; then
    ROOT_DIR="$SCRIPT_REPO_ROOT"
else
    printf 'Unable to infer monorepo root from script location: %s\n' "$SCRIPT_DIR" >&2
    exit 1
fi

ensure_member_repo() {
    local repo_name="$1"
    local repo_dir="$ROOT_DIR/$repo_name"
    local target_branch
    local current_branch
    target_branch="$(repo_target_branch "$repo_name")"

    if [[ -d "$repo_dir/.git" ]]; then
        printf 'Updating existing checkout: %s\n' "$repo_name"
        current_branch="$("$GIT_BINARY" -C "$repo_dir" branch --show-current)"

        if [[ "$current_branch" != "$target_branch" ]]; then
            "$GIT_BINARY" -C "$repo_dir" fetch --depth=1 origin "$target_branch" --quiet
            "$GIT_BINARY" -C "$repo_dir" checkout -B "$target_branch" --track "origin/$target_branch" >/dev/null
        fi

        if "$GIT_BINARY" -C "$repo_dir" -c pull.rebase=false pull --ff-only --quiet origin "$target_branch" >/dev/null 2>&1; then
            printf 'Updated: %s\n' "$repo_name"
        else
            printf 'Skipping pull for %s (local changes, divergent branch, detached HEAD, or no upstream)\n' "$repo_name" >&2
        fi
        return
    fi

    if [[ -e "$repo_dir" ]]; then
        printf 'Refusing to overwrite existing path: %s\n' "$repo_dir" >&2
        exit 1
    fi

    printf 'Cloning %s/%s.git -> %s\n' "$GITHUB_BASE" "$repo_name" "$repo_name"
    "$GIT_BINARY" clone --branch "$target_branch" "$GITHUB_BASE/$repo_name.git" "$repo_dir"
}

for repo_name in "${REPO_NAMES[@]}"; do
    ensure_member_repo "$repo_name"
done

for repo_name in "${REPO_NAMES[@]}"; do
    ensure_setup_link "$repo_name"
done

cd "$ROOT_DIR"
deactivate || true
rm -Rf ./*/.venv   # delete all sub-repo venvs, the monorepo venv needs to take precedence

uv venv --allow-existing "$ROOT_DIR/.venv"
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
bootstrap_build_dependencies
sync_workspace
echo
echo
echo "[√] Monorepo setup complete, cloned and pulled: ${REPO_NAMES[*]}"
echo "    MONOREPO_ROOT=$ROOT_DIR"
echo "    VIRTUAL_ENV=$VIRTUAL_ENV"
echo "    PYTHON_BIN=$VIRTUAL_ENV/bin/python"
echo
echo "TIPS:"
echo " - Use 'uv run ...' inside member repos for package work; the root uv.lock owns this workspace"
echo " - Always read $ROOT_DIR/README.md into context before starting any work"
