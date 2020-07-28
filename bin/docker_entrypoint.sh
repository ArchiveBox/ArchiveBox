#!/usr/bin/env bash

COMMAND="$*"

# Autodetect UID,GID of host user based on ownership of files in the data volume
DATA_DIR="${DATA_DIR:-/data}"
ARCHIVEBOX_USER="${ARCHIVEBOX_USER:-archivebox}"

USID=$(stat --format="%u" "$DATA_DIR")
GRID=$(stat --format="%g" "$DATA_DIR")

# If user is not root, modify the archivebox user+files to have the same uid,gid
if [[ "$USID" != 0 && "$GRID" != 0 ]]; then
    usermod -u "$USID" "$ARCHIVEBOX_USER"
    groupmod -g "$GRID" "$ARCHIVEBOX_USER"
    chown -R "$USID":"$GRID" "/home/$ARCHIVEBOX_USER"
    chown "$USID":"$GRID" "$DATA_DIR"
    chown "$USID":"$GRID" "$DATA_DIR/*" > /dev/null 2>&1 || true
fi

# run django as the new archivebox user
# any files touched will have the same uid,gid
# inside docker and outside docker on the host
gosu "$ARCHIVEBOX_USER" bash -c "$COMMAND"
# e.g. "archivebox server"
