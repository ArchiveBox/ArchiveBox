#!/usr/bin/env bash

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

# Run commands as the new archivebox user in Docker.
#   Any files touched will have the same uid & gid
#   inside Docker and outside on the host machine.
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
