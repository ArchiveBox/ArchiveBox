#!/bin/bash
# /opt/archivebox/install.sh - installs/upgrades archivebox into its virtualenv
# Called by the postinstall script and can be run manually to upgrade

set -e

ARCHIVEBOX_VENV="/opt/archivebox/venv"
ARCHIVEBOX_VERSION="${ARCHIVEBOX_VERSION:-}"

echo "[+] Setting up ArchiveBox virtualenv in $ARCHIVEBOX_VENV..."

# Create the virtualenv if it doesn't exist
if [ ! -d "$ARCHIVEBOX_VENV" ]; then
    python3 -m venv "$ARCHIVEBOX_VENV"
fi

# Upgrade pip inside the virtualenv
"$ARCHIVEBOX_VENV/bin/python3" -m pip install --quiet --upgrade pip setuptools

# Install or upgrade archivebox (pinned to .deb version if set)
if [ -n "$ARCHIVEBOX_VERSION" ]; then
    echo "[+] Installing archivebox==$ARCHIVEBOX_VERSION..."
    "$ARCHIVEBOX_VENV/bin/pip" install --quiet --upgrade "archivebox==$ARCHIVEBOX_VERSION"
else
    echo "[+] Installing latest archivebox..."
    "$ARCHIVEBOX_VENV/bin/pip" install --quiet --upgrade archivebox
fi

echo "[√] ArchiveBox installed successfully."
echo "    Run 'archivebox version' to verify."
