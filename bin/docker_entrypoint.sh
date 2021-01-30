#!/usr/bin/env bash

DATA_DIR="${DATA_DIR:-/data}"
ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"

# Set the archivebox user UID & GID
if [[ -n "$PUID" && "$PUID" != 0 ]]; then
    usermod -u "$PUID" "$ARCHIVEBOX_USER" > /dev/null 2>&1
fi
if [[ -n "$PGID" && "$PGID" != 0 ]]; then
    groupmod -g "$PGID" "$ARCHIVEBOX_USER" > /dev/null 2>&1
fi

# Set the permissions of the data dir to match the archivebox user
if [[ -d "$DATA_DIR/archive" ]]; then
    # check data directory permissions
    if [[ ! "$(stat -c %u $DATA_DIR/archive)" = "$(id -u archivebox)" ]]; then
        echo "Change in ownership detected, please be patient while we chown existing files"
        echo "This could take some time..."
        chown $ARCHIVEBOX_USER:$ARCHIVEBOX_USER -R "$DATA_DIR"
    fi
else
    # create data directory
    mkdir -p "$DATA_DIR"
    chown -R $ARCHIVEBOX_USER:$ARCHIVEBOX_USER "$DATA_DIR"
fi
chown $ARCHIVEBOX_USER:$ARCHIVEBOX_USER "$DATA_DIR"


# Drop permissions to run commands as the archivebox user
if [[ "$1" == /* || "$1" == "echo" || "$1" == "archivebox" ]]; then
    # arg 1 is a binary, execute it verbatim
    # e.g. "archivebox init"
    #      "/bin/bash"
    #      "echo"
    gosu "$ARCHIVEBOX_USER" bash -c "$*"
else
    # no command given, assume args were meant to be passed to archivebox cmd
    # e.g. "add https://example.com"
    #      "manage createsupseruser"
    #      "server 0.0.0.0:8000"
    gosu "$ARCHIVEBOX_USER" bash -c "archivebox $*"
fi
