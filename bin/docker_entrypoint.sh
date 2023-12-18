#!/bin/bash

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# set -o xtrace
set -o errexit
set -o errtrace
set -o pipefail
IFS=$'\n'

# Load global config (set by Dockerfile during image build time, not intended to be customized by users at runtime)
export DATA_DIR="${DATA_DIR:-/data}"
export ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"

# Global default PUID and PGID if data dir is empty and no intended PUID+PGID is set manually by user
export DEFAULT_PUID=911
export DEFAULT_PGID=911

# If user tires to set PUID and PGID to root values manually, catch and reject because root is not allowed
if [[ "$PUID" == "0" ]] || [[ "$PGID" == "0" ]]; then
    echo -e "\n[X] Error: Got PUID=$PUID and PGID=$PGID but ArchiveBox is not allowed to be run as root, please change or unset PUID & PGID and try again." >&2
    echo -e "    Hint: some NFS/SMB/FUSE/etc. filesystems force-remap all permissions, leave PUID/PGID blank" >&2
    echo -e "          or set PUID/PGID to the same value as the user/group they remap to (e.g. $DEFAULT_PUID:$DEFAULT_PGID)." >&2
    echo -e "    https://linux.die.net/man/8/mount.cifs#:~:text=does%20not%20provide%20unix%20ownership" >&2
    exit 3
fi

# If data directory already exists, autodetect detect owner by looking at files within
export DETECTED_PUID="$(stat -c '%u' "$DATA_DIR/logs/errors.log" 2>/dev/null || echo "$DEFAULT_PUID")"
export DETECTED_PGID="$(stat -c '%g' "$DATA_DIR/logs/errors.log" 2>/dev/null || echo "$DEFAULT_PGID")"

# If data directory exists but is owned by root, use defaults instead of root because root is not allowed
[[ "$DETECTED_PUID" == "0" ]] && export DETECTED_PUID="$DEFAULT_PUID"
[[ "$DETECTED_PGID" == "0" ]] && export DETECTED_PGID="$DEFAULT_PGID"


# Set the archivebox user to use the configured UID & GID
# prefer PUID and PGID env vars passsed in explicitly, falls back to autodetected values or global defaults
usermod -o -u "${PUID:-$DETECTED_PUID}" "$ARCHIVEBOX_USER" > /dev/null 2>&1
groupmod -o -g "${PGID:-$DETECTED_PGID}" "$ARCHIVEBOX_USER" > /dev/null 2>&1

# re-set PUID and PGID to values reported by system instead of values we tried to set,
# in case wonky filesystems or Docker setups try to play UID/GID remapping tricks on us
export PUID="$(id -u archivebox)"
export PGID="$(id -g archivebox)"

# Check the permissions of the data dir (or create if it doesn't exist)
if [[ -d "$DATA_DIR/archive" ]]; then
    if touch "$DATA_DIR/archive/.permissions_test_safe_to_delete" 2>/dev/null; then
        # It's fine, we are able to write to the data directory (as root inside the container)
        rm -f "$DATA_DIR/archive/.permissions_test_safe_to_delete"
        # echo "[√] Permissions are correct"
    else
     # the only time this fails is if the host filesystem doesn't allow us to write as root (e.g. some NFS mapall/maproot problems, connection issues, drive dissapeared, etc.)
        echo -e "\n[X] Error: archivebox user (PUID=$PUID) is not able to write to your ./data dir (currently owned by $(stat -c '%u' "$DATA_DIR"):$(stat -c '%g' "$DATA_DIR")." >&2
        echo -e "    Change ./data to be owned by PUID=$PUID PGID=$PGID on the host and retry:" >&2
        echo -e "       \$ chown -R $PUID:$PGID ./data\n" >&2
        echo -e "    Configure the PUID & PGID environment variables to change the desired owner:" >&2
        echo -e "       https://docs.linuxserver.io/general/understanding-puid-and-pgid\n" >&2
        exit 3
    fi
else
    # create data directory
    mkdir -p "$DATA_DIR/logs"
fi

# force set the ownership of the data dir contents to the archivebox user and group
# this is needed because Docker Desktop often does not map user permissions from the host properly
chown $PUID:$PGID "$DATA_DIR"
chown $PUID:$PGID "$DATA_DIR"/*

# also chown BROWSERS_DIR because otherwise 'archivebox setup' wont be able to install chrome at runtime
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/browsers}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
chown $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"
touch "$PLAYWRIGHT_BROWSERS_PATH"/.permissions_test_safe_to_delete
chown $PUID:$PGID "$PLAYWRIGHT_BROWSERS_PATH"/*.*
rm -f "$PLAYWRIGHT_BROWSERS_PATH"/.permissions_test_safe_to_delete


# (this check is written in blood, QEMU silently breaks things in ways that are not obvious)
export IN_QEMU="$(pmap 1 | grep qemu | wc -l | grep -E '^0$' >/dev/null && echo 'False' || echo 'True')"
if [[ "$IN_QEMU" == 'True' ]]; then
    echo -e "\n[!] Warning: Running $(uname -m) emulated container in QEMU, some things will break!" >&2
    echo -e "    chromium (screenshot, pdf, dom), singlefile, and any dependencies that rely on inotify will not run in QEMU." >&2
    echo -e "    See here for more info: https://github.com/microsoft/playwright/issues/17395#issuecomment-1250830493\n" >&2
fi


# Drop permissions to run commands as the archivebox user
if [[ "$1" == /* || "$1" == "bash" || "$1" == "sh" || "$1" == "echo" || "$1" == "cat" || "$1" == "archivebox" ]]; then
    # handle "docker run archivebox /some/non-archivebox/command --with=some args" by passing args directly to bash -c
    # e.g. "docker run archivebox /venv/bin/archivebox-alt init"
    #      "docker run archivebox /bin/bash -c '...'"
    #      "docker run archivebox echo test"
    exec gosu "$PUID" bash -c "$*"
else
    # handle "docker run archivebox add some subcommand --with=args abc" by calling archivebox to run as args as CLI subcommand
    # e.g. "docker run archivebox add --depth=1 https://example.com"
    #      "docker run archivebox manage createsupseruser"
    #      "docker run archivebox server 0.0.0.0:8000"
    exec gosu "$PUID" bash -c "archivebox $*"
fi
