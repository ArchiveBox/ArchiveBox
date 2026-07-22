#!/bin/bash

# This Docker ENTRYPOINT script is called by `docker run archivebox ...` or `docker compose run archivebox ...`.
# It takes a CMD as $* shell arguments and runs it following these setup steps:

# - Set the archivebox user to match the existing /data owner when possible
#     1. use the first non-root owner detected from existing collection files
#     2. fall back to the image's default archivebox uid/gid when /data is root-owned
# - Create a new /data dir if necessary and set the correct ownership on it
# - Create a new /browsers dir if necessary and set the correct ownership on it
# - Check whether we're running inside QEMU emulation and show a warning if so.
# - Check that enough free space is available on / and /data
# - Drop down to archivebox user permissions and execute passed CMD command.

# Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
shopt -s nullglob
set -o errexit
set -o errtrace
set -o pipefail
# Prevent crashed browser/subprocess core dumps from filling snapshot folders.
ulimit -c 0 >/dev/null 2>&1 || true

# Load global invariants (set by Dockerfile during image build time, not intended to be customized by users at runtime)
export DATA_DIR="${DATA_DIR:-/data}"
export CONFIG_DIR="${CONFIG_DIR:-/opt/archivebox}"
export TMP_DIR="${TMP_DIR:-/tmp/archivebox}"
export ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-/opt/archivebox/lib}"
export ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"
export PERSONAS_DIR="${PERSONAS_DIR:-$DATA_DIR/personas}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ABXPKG_LIB_DIR/playwright/cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$ABXPKG_LIB_DIR/cache}"
export ABXBUS_CACHE_DIR="${ABXBUS_CACHE_DIR:-$XDG_CACHE_HOME/abxbus}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$XDG_CACHE_HOME/uv}"

# Global default uid/gid used when /data is empty or root-owned.
export DEFAULT_ARCHIVEBOX_UID="${DEFAULT_ARCHIVEBOX_UID:-911}"
export DEFAULT_ARCHIVEBOX_GID="${DEFAULT_ARCHIVEBOX_GID:-911}"

detect_data_owner() {
    local path uid gid
    for path in "$DATA_DIR/ArchiveBox.conf" "$DATA_DIR/index.sqlite3" "$DATA_DIR/logs" "$DATA_DIR/archive" "$DATA_DIR"; do
        if [[ -e "$path" ]]; then
            uid="$(stat -c '%u' "$path" 2>/dev/null || echo "$DEFAULT_ARCHIVEBOX_UID")"
            gid="$(stat -c '%g' "$path" 2>/dev/null || echo "$DEFAULT_ARCHIVEBOX_GID")"
            if [[ "$uid" != "0" && "$gid" != "0" ]]; then
                echo "$uid:$gid"
                return
            fi
        fi
    done
    echo "$DEFAULT_ARCHIVEBOX_UID:$DEFAULT_ARCHIVEBOX_GID"
}

export DETECTED_OWNER="$(detect_data_owner)"
export TARGET_UID="${DETECTED_OWNER%%:*}"
export TARGET_GID="${DETECTED_OWNER##*:}"

if [[ "$(id -u)" == "0" ]]; then
    # Root is only used for startup permission repair. ArchiveBox/Chrome run as
    # the existing collection owner, or as the image default user for root-owned
    # /data, so application code never needs to know about Docker uid mapping.
    groupmod -o -g "$TARGET_GID" "$ARCHIVEBOX_USER" > /dev/null 2>&1 || {
        echo -e "\n[X] Error: Failed to set $ARCHIVEBOX_USER group to gid=$TARGET_GID." > /dev/stderr
        exit 3
    }
    usermod -o -u "$TARGET_UID" -g "$TARGET_GID" "$ARCHIVEBOX_USER" > /dev/null 2>&1 || {
        echo -e "\n[X] Error: Failed to set $ARCHIVEBOX_USER user to uid=$TARGET_UID gid=$TARGET_GID." > /dev/stderr
        exit 3
    }

    export TARGET_UID="$(id -u "$ARCHIVEBOX_USER")"
    export TARGET_GID="$(id -g "$ARCHIVEBOX_USER")"
else
    export TARGET_UID="$(id -u)"
    export TARGET_GID="$(id -g)"
fi

# Check if user attempted to run it in the root of their home folder or hard drive (common mistake)
if [[ -d "$DATA_DIR/Documents" || -d "$DATA_DIR/.config" || -d "$DATA_DIR/usr" || -f "$DATA_DIR/.bashrc" || -f "$DATA_DIR/.zshrc" ]]; then
    echo -e "\n[X] ERROR: ArchiveBox was run from inside a home folder"
    echo -e "      Make sure you are inside an existing collection directory or a new empty directory and try again"
    exit 3
fi

chown_if_needed() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    [[ "$(id -u)" == "0" ]] || return 0
    [[ "$(stat -c '%u:%g' "$path" 2>/dev/null || true)" == "$TARGET_UID:$TARGET_GID" ]] && return 0
    chown -h "$TARGET_UID:$TARGET_GID" "$path" 2>/dev/null || true
}

chmod_if_possible() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    chmod u+rwX,g+rwX "$path" 2>/dev/null || true
}

ensure_dir() {
    local path="$1"
    mkdir -p "$path" 2>/dev/null || true
    chown_if_needed "$path"
    chmod_if_possible "$path"
}

ensure_file_owner() {
    local path="$1"
    [[ -e "$path" ]] || return 0
    chown_if_needed "$path"
    chmod_if_possible "$path"
}

ensure_runtime_tree() {
    local path="$1"
    mkdir -p "$path" 2>/dev/null || true
    [[ -e "$path" ]] || return 0
    if [[ "$(id -u)" == "0" ]] && [[ "$(stat -c '%u:%g' "$path" 2>/dev/null || true)" != "$TARGET_UID:$TARGET_GID" ]]; then
        chown -R "$TARGET_UID:$TARGET_GID" "$path" 2>/dev/null || true
    fi
    chmod_if_possible "$path"
}

ensure_runtime_tmp_tree() {
    mkdir -p "$TMP_DIR" 2>/dev/null || true
    [[ -e "$TMP_DIR" ]] || return 0
    if [[ "$(id -u)" == "0" ]]; then
        chown -R "$TARGET_UID:$TARGET_GID" "$TMP_DIR" 2>/dev/null || true
    fi
    chmod_if_possible "$TMP_DIR"
}

ensure_small_runtime_tree() {
    local path="$1"
    mkdir -p "$path" 2>/dev/null || true
    [[ -e "$path" ]] || return 0
    if [[ "$(id -u)" == "0" ]]; then
        chown -R "$TARGET_UID:$TARGET_GID" "$path" 2>/dev/null || true
    fi
    chmod -R u+rwX,g+rwX "$path" 2>/dev/null || true
}

run_as_archivebox() {
    if [[ "$(id -u)" == "0" ]]; then
        setpriv --reuid="$ARCHIVEBOX_USER" --regid="$ARCHIVEBOX_USER" --init-groups "$@"
    else
        "$@"
    fi
}

permission_error() {
    local path="$1"
    echo -e "\n[X] Error: archivebox user (uid=$TARGET_UID gid=$TARGET_GID) cannot write to $path." > /dev/stderr
    echo -e "    Current owner is $(stat -c '%u:%g' "$path" 2>/dev/null || echo 'unknown')." > /dev/stderr
    echo -e "    Fix ownership on the host so /data is writable by the intended archivebox user:" > /dev/stderr
    echo -e "       chown -R $TARGET_UID:$TARGET_GID ./data   # only if you intentionally want to repair the full tree" > /dev/stderr
    exit 3
}

# Create and repair only the small set of top-level writable paths. Do not recurse
# through /data/archive; large collections can take days to recursively chown/chmod.
ensure_dir "$DATA_DIR"
ensure_dir "$CONFIG_DIR"
ensure_dir "$DATA_DIR/logs"
ensure_dir "$DATA_DIR/sources"
ensure_dir "$DATA_DIR/archive"
ensure_dir "$DATA_DIR/archive/users"
ensure_dir "$PERSONAS_DIR"
ensure_dir "$PERSONAS_DIR/Default"
ensure_dir "$PERSONAS_DIR/Default/chrome_profile"
[[ -e "$DATA_DIR/users" ]] && ensure_dir "$DATA_DIR/users"
ensure_file_owner "$DATA_DIR/index.sqlite3"
ensure_file_owner "$DATA_DIR/ArchiveBox.conf"
ensure_file_owner "$CONFIG_DIR/config.env"
ensure_file_owner "$CONFIG_DIR/derived.env"

run_as_archivebox touch "$DATA_DIR/logs/.permissions_test_safe_to_delete" 2>/dev/null || permission_error "$DATA_DIR/logs"
rm -f "$DATA_DIR/logs/.permissions_test_safe_to_delete"
run_as_archivebox touch "$DATA_DIR/archive/.permissions_test_safe_to_delete" 2>/dev/null || permission_error "$DATA_DIR/archive"
rm -f "$DATA_DIR/archive/.permissions_test_safe_to_delete"
run_as_archivebox touch "$PERSONAS_DIR/Default/chrome_profile/.permissions_test_safe_to_delete" 2>/dev/null || permission_error "$PERSONAS_DIR/Default/chrome_profile"
rm -f "$PERSONAS_DIR/Default/chrome_profile/.permissions_test_safe_to_delete"

# check if novnc x11 $DISPLAY is available
export DISPLAY="${DISPLAY:-"novnc:0.0"}"
if ! xdpyinfo > /dev/null 2>&1; then
    # cant connect to x11 display, unset it so that chrome doesn't try to connect to it and hang indefinitely
    unset DISPLAY
fi

# Active browser processes do not survive container restarts, but their lock
# files can. Clear stale browser state before dropping privileges.
find "$PERSONAS_DIR" -type f \( \
    -name "SingletonLock" \
    -o -name "SingletonSocket" \
    -o -name "SingletonCookie" \
    -o -name "DevToolsActivePort" \
    -o -name ".launch.lock" \
    -o -name ".target.lock" \
\) -delete >/dev/null 2>&1 || true
find /tmp "$TMP_DIR" -maxdepth 1 -type d -name "archivebox-chrome-profile.*" -mmin +30 -exec rm -rf {} + >/dev/null 2>&1 || true
    

ensure_dir "/home/$ARCHIVEBOX_USER"
ensure_small_runtime_tree "$ABXBUS_CACHE_DIR"
ensure_small_runtime_tree "$ABXBUS_CACHE_DIR/semaphores"
ensure_small_runtime_tree "$UV_CACHE_DIR"
ensure_runtime_tree "$PLAYWRIGHT_BROWSERS_PATH"
ensure_runtime_tmp_tree
ensure_runtime_tree "$ABXPKG_LIB_DIR"
run_as_archivebox touch "$ABXBUS_CACHE_DIR/semaphores/.permissions_test_safe_to_delete" 2>/dev/null || permission_error "$ABXBUS_CACHE_DIR/semaphores"
rm -f "$ABXBUS_CACHE_DIR/semaphores/.permissions_test_safe_to_delete"
run_as_archivebox touch "$UV_CACHE_DIR/.permissions_test_safe_to_delete" 2>/dev/null || permission_error "$UV_CACHE_DIR"
rm -f "$UV_CACHE_DIR/.permissions_test_safe_to_delete"

# (this check is written in blood in 2023, QEMU silently breaks things in ways that are not obvious)
export IN_QEMU="$(pmap 1 | grep qemu >/dev/null && echo 'True' || echo 'False')"
if [[ "$IN_QEMU" == "True" ]]; then
    echo -e "\n[!] Warning: Running $(uname -m) docker image using QEMU emulation, some things will break!" > /dev/stderr
    echo -e "    chromium (screenshot, pdf, dom), singlefile, and any dependencies that rely on inotify will not run in QEMU." > /dev/stderr
    echo -e "    See here for more info: https://github.com/microsoft/playwright/issues/17395#issuecomment-1250830493\n" > /dev/stderr
fi

# check disk space free on /, /data, and /data/archive, warn on <500Mb free, error on <100Mb free
export ROOT_USAGE="$(df --output=pcent,avail / | tail -n 1 | xargs)"
export ROOT_USED_PCT="${ROOT_USAGE%%%*}"
export ROOT_AVAIL_KB="$(echo "$ROOT_USAGE" | awk '{print $2}')"
if [[ "$ROOT_AVAIL_KB" -lt 100000 ]]; then
    echo -e "\n[!] Warning: Docker root filesystem is completely out of space! (${ROOT_USED_PCT}% used on /)" > /dev/stderr
    echo -e "    you need to free up at least 100Mb in your Docker VM to continue:" > /dev/stderr
    echo -e "    \$ docker system prune\n" > /dev/stderr
    df -kh / > /dev/stderr
    exit 3
elif [[ "$ROOT_USED_PCT" -ge 99 ]] || [[ "$ROOT_AVAIL_KB" -lt 500000 ]]; then
    echo -e "\n[!] Warning: Docker root filesystem is running out of space! (${ROOT_USED_PCT}% used on /)" > /dev/stderr
    echo -e "    you may need to free up space in your Docker VM soon:" > /dev/stderr
    echo -e "    \$ docker system prune\n" > /dev/stderr
    df -kh / > /dev/stderr
fi

export DATA_USAGE="$(df --output=pcent,avail "$DATA_DIR" | tail -n 1 | xargs)"
export DATA_USED_PCT="${DATA_USAGE%%%*}"
export DATA_AVAIL_KB="$(echo "$DATA_USAGE" | awk '{print $2}')"
if [[ "$DATA_AVAIL_KB" -lt 100000 ]]; then
    echo -e "\n[!] Warning: Docker data volume is completely out of space! (${DATA_USED_PCT}% used on $DATA_DIR)" > /dev/stderr
    echo -e "    you need to free up at least 100Mb on the drive holding your data directory" > /dev/stderr
    echo -e "    \$ ncdu -x data\n" > /dev/stderr
    df -kh "$DATA_DIR" > /dev/stderr
    sleep 5
elif [[ "$DATA_USED_PCT" -ge 99 ]] || [[ "$ROOT_AVAIL_KB" -lt 500000 ]]; then
    echo -e "\n[!] Warning: Docker data volume is running out of space! (${DATA_USED_PCT}% used on $DATA_DIR)" > /dev/stderr
    echo -e "    you may need to free up space on the drive holding your data directory soon" > /dev/stderr
    echo -e "    \$ ncdu -x data\n" > /dev/stderr
    df -kh "$DATA_DIR" > /dev/stderr
else
    # data/ has space available, but check data/archive separately, because it might be on a network mount or external drive
    if [[ -d "$DATA_DIR/archive" ]]; then
        export ARCHIVE_USAGE="$(df --output=pcent,avail "$DATA_DIR/archive" | tail -n 1 | xargs)"
        export ARCHIVE_USED_PCT="${ARCHIVE_USAGE%%%*}"
        export ARCHIVE_AVAIL_KB="$(echo "$ARCHIVE_USAGE" | awk '{print $2}')"
        if [[ "$ARCHIVE_AVAIL_KB" -lt 100000 ]]; then
            echo -e "\n[!] Warning: data/archive folder is completely out of space! (${ARCHIVE_USED_PCT}% used on $DATA_DIR/archive)" > /dev/stderr
            echo -e "    you need to free up at least 100Mb on the drive holding your data/archive directory" > /dev/stderr
            echo -e "    \$ ncdu -x data/archive\n" > /dev/stderr
            df -kh "$DATA_DIR/archive" > /dev/stderr
            sleep 5
        elif [[ "$ARCHIVE_USED_PCT" -ge 99 ]] || [[ "$ROOT_AVAIL_KB" -lt 500000 ]]; then
            echo -e "\n[!] Warning: data/archive folder is running out of space! (${ARCHIVE_USED_PCT}% used on $DATA_DIR/archive)" > /dev/stderr
            echo -e "    you may need to free up space on the drive holding your data/archive directory soon" > /dev/stderr
            echo -e "    \$ ncdu -x data/archive\n" > /dev/stderr
            df -kh "$DATA_DIR/archive" > /dev/stderr
        fi
    fi
fi

export ARCHIVEBOX_BIN_PATH="$(command -v archivebox)"

# Drop permissions to run commands as the archivebox user
if [[ "$1" == /* || "$1" == "bash" || "$1" == "sh" || "$1" == "echo" || "$1" == "cat" || "$1" == "whoami" || "$1" == "archivebox" ]]; then
    # handle "docker run archivebox /bin/somecommand --with=some args" by passing args directly to bash -c
    # e.g. "docker run archivebox archivebox init:
    #      "docker run archivebox /venv/bin/ipython3"
    #      "docker run archivebox /bin/bash -c '...'"
    #      "docker run archivebox cat /VERSION.txt"
    if [[ "$(id -u)" == "0" ]]; then
        exec setpriv --reuid="$ARCHIVEBOX_USER" --regid="$ARCHIVEBOX_USER" --init-groups /bin/bash -c "exec $(printf ' %q' "$@")"
    else
        exec /bin/bash -c "exec $(printf ' %q' "$@")"
    fi
    # printf requotes shell parameters properly https://stackoverflow.com/a/39463371/2156113
    # setpriv spawns an ephemeral bash process owned by archivebox user (bash wrapper is needed to load env vars, PATH, and setup terminal TTY)
    # outermost exec hands over current process ID to inner bash process, inner exec hands over inner bash PID to user's command
else
    # handle "docker run archivebox add some subcommand --with=args abc" by calling archivebox to run as args as CLI subcommand
    # e.g. "docker run archivebox help"
    #      "docker run archivebox add --depth=1 https://example.com"
    #      "docker run archivebox manage createsupseruser"
    #      "docker run archivebox server 0.0.0.0:8000"
    if [[ "$(id -u)" == "0" ]]; then
        exec setpriv --reuid="$ARCHIVEBOX_USER" --regid="$ARCHIVEBOX_USER" --init-groups "$ARCHIVEBOX_BIN_PATH" "$@"
    else
        exec "$ARCHIVEBOX_BIN_PATH" "$@"
    fi
fi
