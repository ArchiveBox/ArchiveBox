#!/bin/bash

# This Docker ENTRYPOINT script is called by `docker run archivebox ...` or `docker compose run archivebox ...`.
# It takes a CMD as $* shell arguments and runs it following these setup steps:

# - Set the archivebox user to use the correct PUID & PGID
#     1. highest precedence is for valid PUID and PGID env vars passed in explicitly
#     2. fall back to DETECTED_PUID of files found within existing data dir
#     3. fall back to DEFAULT_PUID if no data dir or its owned by root
# - Create a new /data dir if necessary and set the correct ownership on it
# - Create a new /browsers dir if necessary and set the correct ownership on it
# - Check whether we're running inside QEMU emulation and show a warning if so.
# - Check that enough free space is available on / and /data
# - Drop down to archivebox user permissions and execute passed CMD command.

# Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# set -o xtrace
# set -o nounset
shopt -s nullglob
set -o errexit
set -o errtrace
set -o pipefail
# IFS=$'\n'

# Prevent crashed browser/subprocess core dumps from filling snapshot folders.
ulimit -c 0 >/dev/null 2>&1 || true

# Load global invariants (set by Dockerfile during image build time, not intended to be customized by users at runtime)
export DATA_DIR="${DATA_DIR:-/data}"
export TMP_DIR="${TMP_DIR:-/tmp/archivebox}"
export LIB_DIR="${LIB_DIR:-/opt/archivebox/lib}"
export ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-$LIB_DIR}"
export ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"
export PERSONAS_DIR="${PERSONAS_DIR:-$DATA_DIR/personas}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/browsers}"

# Global default PUID and PGID if data dir is empty and no intended PUID+PGID is set manually by user
export DEFAULT_PUID=911
export DEFAULT_PGID=911

detect_data_owner() {
    local path uid gid
    for path in "$DATA_DIR/ArchiveBox.conf" "$DATA_DIR/index.sqlite3" "$DATA_DIR/logs" "$DATA_DIR/archive" "$DATA_DIR"; do
        if [[ -e "$path" ]]; then
            uid="$(stat -c '%u' "$path" 2>/dev/null || echo "$DEFAULT_PUID")"
            gid="$(stat -c '%g' "$path" 2>/dev/null || echo "$DEFAULT_PGID")"
            if [[ "$uid" != "0" && "$gid" != "0" ]]; then
                echo "$uid:$gid"
                return
            fi
        fi
    done
    echo "$DEFAULT_PUID:$DEFAULT_PGID"
}

export DETECTED_OWNER="$(detect_data_owner)"
export DETECTED_PUID="${DETECTED_OWNER%%:*}"
export DETECTED_PGID="${DETECTED_OWNER##*:}"
export PUID="${PUID:-$DETECTED_PUID}"
export PGID="${PGID:-$DETECTED_PGID}"
export REQUESTED_PUID="$PUID"
export REQUESTED_PGID="$PGID"

if [[ ! "$PUID" =~ ^[0-9]+$ || ! "$PGID" =~ ^[0-9]+$ ]]; then
    echo -e "\n[X] Error: PUID and PGID must be numeric, got PUID=$PUID PGID=$PGID." > /dev/stderr
    echo -e "    Example: PUID=$(id -u) PGID=$(id -g) docker compose up" > /dev/stderr
    exit 3
fi

# If user tries to set PUID or PGID to root values, keep root only for entrypoint
# setup and run ArchiveBox/Chrome as the default non-root user instead.
if [[ "$PUID" == "0" || "$PGID" == "0" ]]; then
    [[ "$PUID" == "0" ]] && export PUID="$DEFAULT_PUID"
    [[ "$PGID" == "0" ]] && export PGID="$DEFAULT_PGID"
    echo -e "\n[!] Warning: Got PUID=$REQUESTED_PUID PGID=$REQUESTED_PGID, but ArchiveBox/Chrome should not run as root." > /dev/stderr
    echo -e "    The entrypoint will use root only for startup permission repair, then run ArchiveBox as a non-root user." > /dev/stderr
    echo -e "    Using PUID=$PUID PGID=$PGID. See https://docs.linuxserver.io/general/understanding-puid-and-pgid" > /dev/stderr
fi

if [[ "$(id -u)" == "0" ]]; then
    # Set archivebox user and group ids to desired PUID/PGID.
    groupmod -o -g "$PGID" "$ARCHIVEBOX_USER" > /dev/null 2>&1 || {
        echo -e "\n[X] Error: Failed to set $ARCHIVEBOX_USER group to PGID=$PGID." > /dev/stderr
        exit 3
    }
    usermod -o -u "$PUID" -g "$PGID" "$ARCHIVEBOX_USER" > /dev/null 2>&1 || {
        echo -e "\n[X] Error: Failed to set $ARCHIVEBOX_USER user to PUID=$PUID PGID=$PGID." > /dev/stderr
        exit 3
    }

    export PUID="$(id -u "$ARCHIVEBOX_USER")"
    export PGID="$(id -g "$ARCHIVEBOX_USER")"
else
    export PUID="$(id -u)"
    export PGID="$(id -g)"
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
    [[ "$(stat -c '%u:%g' "$path" 2>/dev/null || true)" == "$PUID:$PGID" ]] && return 0
    chown -h "$PUID:$PGID" "$path" 2>/dev/null || true
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
    if [[ "$(id -u)" == "0" ]] && [[ "$(stat -c '%u:%g' "$path" 2>/dev/null || true)" != "$PUID:$PGID" ]]; then
        chown -R "$PUID:$PGID" "$path" 2>/dev/null || true
    fi
    chmod_if_possible "$path"
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
    echo -e "\n[X] Error: archivebox user (PUID=$PUID PGID=$PGID) cannot write to $path." > /dev/stderr
    echo -e "    Current owner is $(stat -c '%u:%g' "$path" 2>/dev/null || echo 'unknown')." > /dev/stderr
    echo -e "    Fix ownership on the host, or set PUID/PGID to match the mount owner:" > /dev/stderr
    echo -e "       PUID=$PUID PGID=$PGID docker compose up" > /dev/stderr
    echo -e "       chown -R $PUID:$PGID ./data   # only if you intentionally want to repair the full tree" > /dev/stderr
    echo -e "    https://docs.linuxserver.io/general/understanding-puid-and-pgid" > /dev/stderr
    exit 3
}

# Create and repair only the small set of top-level writable paths. Do not recurse
# through /data/archive; large collections can take days to recursively chown/chmod.
ensure_dir "$DATA_DIR"
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
ensure_runtime_tree "$PLAYWRIGHT_BROWSERS_PATH"
ensure_runtime_tree "$TMP_DIR"
ensure_runtime_tree "$LIB_DIR"

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

# set DBUS_SYSTEM_BUS_ADDRESS & DBUS_SESSION_BUS_ADDRESS
# (dbus is not actually needed, it makes chrome log fewer warnings but isn't worth making our docker images bigger)
# service dbus start >/dev/null 2>&1 &
# export $(dbus-launch --close-stderr)


export ARCHIVEBOX_BIN_PATH="$(which archivebox)"

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
