#!/bin/bash

# This Docker ENTRYPOINT script is called by `docker run archivebox ...` or `docker compose run archivebox ...`.
# It takes a CMD as $* shell arguments and runs it following these setup steps:

# - Set the archivebox user to use the correct PUID & PGID
#     1. highest precedence is for valid PUID and PGID env vars passsed in explicitly
#     2. fall back to DETECTED_PUID of files found within existing data dir
#     3. fall back to DEFAULT_PUID if no data dir or its owned by root
# - Create a new /data dir if necessary and set the correct ownership on it
# - Create a new /browsers dir if necessary and set the correct ownership on it
# - Check whether we're running inside QEMU emulation and show a warning if so.
# - Check that enough free space is available on / and /data
# - Drop down to archivebox user permisisons and execute passed CMD command.

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

# Load global invariants (set by Dockerfile during image build time, not intended to be customized by users at runtime)
export DATA_DIR="${DATA_DIR:-/data}"
export ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"

# Global default PUID and PGID if data dir is empty and no intended PUID+PGID is set manually by user
export DEFAULT_PUID=911
export DEFAULT_PGID=911

# If user tires to set PUID and PGID to root values manually, catch and reject because root is not allowed
if [[ "$PUID" == "0" ]]; then
    echo -e "\n[X] Error: Got PUID=$PUID and PGID=$PGID but ArchiveBox is not allowed to be run as root, please change or unset PUID & PGID and try again." > /dev/stderr
    echo -e "    Hint: some NFS/SMB/FUSE/etc. filesystems force-remap/ignore all permissions," > /dev/stderr
        echo -e "          leave PUID/PGID unset, disable root_squash, or use values the drive prefers (default is $DEFAULT_PUID:$DEFAULT_PGID)" > /dev/stderr
        echo -e "    https://linux.die.net/man/8/mount.cifs#:~:text=does%20not%20provide%20unix%20ownership" > /dev/stderr
    exit 3
fi

# If data directory already exists, autodetect detect owner by looking at files within
export DETECTED_PUID="$(stat -c '%u' "$DATA_DIR/logs/errors.log" 2>/dev/null || echo "$DEFAULT_PUID")"
export DETECTED_PGID="$(stat -c '%g' "$DATA_DIR/logs/errors.log" 2>/dev/null || echo "$DEFAULT_PGID")"

# If data directory exists but is owned by root, use defaults instead of root because root is not allowed
[[ "$DETECTED_PUID" == "0" ]] && export DETECTED_PUID="$DEFAULT_PUID"
# (GUID / DETECTED_GUID is allowed to be 0 though)

# Set archivebox user and group ids to desired PUID/PGID
usermod -o -u "${PUID:-$DETECTED_PUID}" "$ARCHIVEBOX_USER" > /dev/null 2>&1
groupmod -o -g "${PGID:-$DETECTED_PGID}" "$ARCHIVEBOX_USER" > /dev/null 2>&1

# re-set PUID and PGID to values reported by system instead of values we tried to set,
# in case wonky filesystems or Docker setups try to play UID/GID remapping tricks on us
export PUID="$(id -u archivebox)"
export PGID="$(id -g archivebox)"

# Check if user attempted to run it in the root of their home folder or hard drive (common mistake)
if [[ -d "$DATA_DIR/Documents" || -d "$DATA_DIR/.config" || -d "$DATA_DIR/usr" || -f "$DATA_DIR/.bashrc" || -f "$DATA_DIR/.zshrc" ]]; then
    echo -e "\n[X] ERROR: ArchiveBox was run from inside a home folder"
    echo -e "      Make sure you are inside an existing collection directory or a new empty directory and try again"
    exit 3
fi

# Check the permissions of the data dir (or create if it doesn't exist)
if [[ -d "$DATA_DIR/archive" ]]; then
    if touch "$DATA_DIR/archive/.permissions_test_safe_to_delete" 2>/dev/null; then
        # It's fine, we are able to write to the data directory (as root inside the container)
        rm -f "$DATA_DIR/archive/.permissions_test_safe_to_delete"
        # echo "[√] Permissions are correct"
    else
     # the only time this fails is if the host filesystem doesn't allow us to write as root (e.g. some NFS mapall/maproot problems, connection issues, drive dissapeared, etc.)
        echo -e "\n[X] Error: archivebox user (PUID=$PUID) is not able to write to your ./data/archive dir (currently owned by $(stat -c '%u' "$DATA_DIR/archive"):$(stat -c '%g' "$DATA_DIR/archive")." > /dev/stderr
        echo -e "    Change ./data to be owned by PUID=$PUID PGID=$PGID on the host and retry:" > /dev/stderr
        echo -e "       \$ chown -R $PUID:$PGID ./data\n" > /dev/stderr
        echo -e "    Configure the PUID & PGID environment variables to change the desired owner:" > /dev/stderr
        echo -e "       https://docs.linuxserver.io/general/understanding-puid-and-pgid\n" > /dev/stderr
        echo -e "    Hint: some NFS/SMB/FUSE/etc. filesystems force-remap/ignore all permissions," > /dev/stderr
        echo -e "          leave PUID/PGID unset, disable root_squash, or use values the drive prefers (default is $DEFAULT_PUID:$DEFAULT_PGID)" > /dev/stderr
        echo -e "    https://linux.die.net/man/8/mount.cifs#:~:text=does%20not%20provide%20unix%20ownership" > /dev/stderr
        exit 3
    fi
else
    # create data directory (and logs, since its the first dir ArchiveBox needs to write to)
    mkdir -p "$DATA_DIR/logs"
fi

# check if novnc x11 $DISPLAY is available
export DISPLAY="${DISPLAY:-"novnc:0.0"}"
if ! xdpyinfo > /dev/null 2>&1; then
    # cant connect to x11 display, unset it so that chrome doesn't try to connect to it and hang indefinitely
    unset DISPLAY
fi

# force set the ownership of the data dir contents to the archivebox user and group
# this is needed because Docker Desktop often does not map user permissions from the host properly
chown $PUID:$PGID "$DATA_DIR"
if ! chown $PUID:$PGID "$DATA_DIR"/* > /dev/null 2>&1; then
    # users may store the ./data/archive folder on a network mount that prevents chmod/chown
    # fallback to chowning everything else in ./data and leaving ./data/archive alone
    find "$DATA_DIR" -type d -not -path "$DATA_DIR/archive*" -exec chown $PUID:$PGID {} \; > /dev/null 2>&1
    find "$DATA_DIR" -type f -not -path "$DATA_DIR/archive/*" -exec chown $PUID:$PGID {} \; > /dev/null 2>&1
fi
    

# also chown BROWSERS_DIR because otherwise 'archivebox setup' wont be able to 'playwright install chromium' at runtime
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/browsers}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH/permissions_test_safe_to_delete"
rm -Rf "$PLAYWRIGHT_BROWSERS_PATH/permissions_test_safe_to_delete"
chown $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"
if [[ -d "$PLAYWRIGHT_BROWSERS_PATH/.links" ]]; then
    chown $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"/*
    chown $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"/.*
    chown -h $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"/.links/*
fi

# also create and chown tmp dir and lib dir (and their default equivalents inside data/)
# mkdir -p "$DATA_DIR"/lib/bin
# chown $PUID:$PGID "$DATA_DIR"/lib "$DATA_DIR"/lib/*
chown $PUID:$PGID "$LIB_DIR" 2>/dev/null
chown $PUID:$PGID "$LIB_DIR/*" 2>/dev/null &

# mkdir -p "$DATA_DIR"/tmp/workers
# chown $PUID:$PGID "$DATA_DIR"/tmp "$DATA_DIR"/tmp/*
chown $PUID:$PGID "$TMP_DIR" 2>/dev/null
chown $PUID:$PGID "$TMP_DIR/*" 2>/dev/null &

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

# symlink etc crontabs into place
mkdir -p "$DATA_DIR"/crontabs
if ! test -L /var/spool/cron/crontabs; then
    # move files from old location into new data dir location
    for existing_file in /var/spool/cron/crontabs/*; do
        mv "$existing_file" "$DATA_DIR/crontabs/"
    done
    # replace old system path with symlink to data dir location
    rm -Rf /var/spool/cron/crontabs
    ln -sf "$DATA_DIR/crontabs" /var/spool/cron/crontabs
fi
chown -R $PUID "$DATA_DIR"/crontabs

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
    exec gosu "$PUID" /bin/bash -c "exec $(printf ' %q' "$@")"
    # printf requotes shell parameters properly https://stackoverflow.com/a/39463371/2156113
    # gosu spawns an ephemeral bash process owned by archivebox user (bash wrapper is needed to load env vars, PATH, and setup terminal TTY)
    # outermost exec hands over current process ID to inner bash process, inner exec hands over inner bash PID to user's command
else
    # handle "docker run archivebox add some subcommand --with=args abc" by calling archivebox to run as args as CLI subcommand
    # e.g. "docker run archivebox help"
    #      "docker run archivebox add --depth=1 https://example.com"
    #      "docker run archivebox manage createsupseruser"
    #      "docker run archivebox server 0.0.0.0:8000"
    exec gosu "$PUID" "$ARCHIVEBOX_BIN_PATH" "$@"
fi
