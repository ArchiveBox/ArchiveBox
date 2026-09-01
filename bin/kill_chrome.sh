#!/usr/bin/env bash

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${LIB_DIR:-$HOME/.config/archivebox/lib}}"
ABXPKG_SPEC="$(UV_LOCK_PATH="$REPO_DIR/uv.lock" uv run --no-cache --no-project python -c 'import os, tomllib; package = next(item for item in tomllib.load(open(os.environ["UV_LOCK_PATH"], "rb"))["package"] if item["name"] == "abxpkg"); wheel = package["wheels"][0]; print("abxpkg @ {}#{}".format(wheel["url"], wheel["hash"].replace(":", "=")))')"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-cache --no-project --with "$ABXPKG_SPEC" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$REPO_DIR/.github/configs/ci-tooling.json:process_binaries" \
    >/dev/null
PS_BINARY="$ABXPKG_LIB_DIR/env/bin/ps"
test -x "$PS_BINARY"
chrome_processes() {
    local pid state command
    shopt -s nocasematch
    while read -r pid state command; do
        [[ -n "$pid" ]] || continue
        if [[ "$command" =~ (google[[:space:]]chrome|google-chrome|chromium-browser|chromium|chrome) ]] \
            && [[ "$command" =~ (remote-debugging-port|remote-debugging-address=127\.0\.0\.1) ]]; then
            printf '%s\t%s\t%s\n' "$pid" "$state" "$command"
        fi
    done < <("$PS_BINARY" -axo pid=,state=,command=)
    shopt -u nocasematch
}

kill_chrome_processes() {
    echo "Searching for Chrome processes listening on 127.0.0.1..."
    local killed=0 pid state command remaining

    while IFS=$'\t' read -r pid state command; do
        [[ -n "$pid" ]] || continue
        echo "Found Chrome process: $pid $command"
        if [[ "$state" == *"Z"* || "$state" == *"D"* || "$state" == *"UNE"* ]]; then
            echo "  WARNING: $pid is in uninterruptible/zombie state ($state) - cannot be killed"
            continue
        fi

        kill "$pid" 2>/dev/null || true
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Force killing $pid with -9..."
            kill -9 "$pid"
        fi
        killed=$((killed + 1))
    done <<<"$(chrome_processes)"

    if [[ "$killed" == "0" ]]; then
        echo "No Chrome processes listening on 127.0.0.1 found (or all are zombie/uninterruptible)"
    else
        echo "Successfully killed $killed Chrome process(es)"
    fi

    echo
    echo "Remaining Chrome processes listening on 127.0.0.1:"
    remaining="$(chrome_processes)"
    if [[ -n "$remaining" ]]; then
        printf '%s\n' "$remaining"
    else
        echo "  (none)"
    fi
}

show_help() {
    cat <<EOF
Kill Chrome/Chromium processes listening on 127.0.0.1

Usage:
  $0 [--help]
EOF
}

case "${1:-}" in
    --help|-h) show_help ;;
    "") kill_chrome_processes ;;
    *)
        echo "[X] Unknown argument: $1" >&2
        show_help >&2
        exit 2
        ;;
esac
