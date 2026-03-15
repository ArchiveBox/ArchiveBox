#!/bin/bash
# /opt/archivebox/install.sh - installs/upgrades archivebox into its virtualenv
# Called by the postinstall script and can be run manually to upgrade

set -e

ARCHIVEBOX_VENV="/opt/archivebox/venv"
ARCHIVEBOX_VERSION="${ARCHIVEBOX_VERSION:-}"

# ArchiveBox requires Python >= 3.13 (per pyproject.toml).
# Prefer python3.13 explicitly; fall back to python3 with a version check.
if command -v python3.13 >/dev/null 2>&1; then
    PYTHON="python3.13"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
    PY_VER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [ "$(echo "$PY_VER 3.13" | awk '{print ($1 >= $2)}')" != "1" ]; then
        echo "[!] Error: ArchiveBox requires Python >= 3.13, but found Python $PY_VER"
        echo "    Install python3.13: sudo apt install python3.13 python3.13-venv"
        exit 1
    fi
else
    echo "[!] Error: python3 not found. Install python3.13: sudo apt install python3.13 python3.13-venv"
    exit 1
fi

echo "[+] Setting up ArchiveBox virtualenv in $ARCHIVEBOX_VENV (using $PYTHON)..."

# Create the virtualenv if it doesn't exist
if [ ! -d "$ARCHIVEBOX_VENV" ]; then
    "$PYTHON" -m venv "$ARCHIVEBOX_VENV"
fi

# Upgrade pip inside the virtualenv
"$ARCHIVEBOX_VENV/bin/python3" -m pip install --quiet --upgrade pip setuptools

# Install or upgrade archivebox.
# ARCHIVEBOX_VERSION is set by postinstall.sh from the .deb package version.
# When run manually without it, install the latest release from PyPI.
if [ -n "$ARCHIVEBOX_VERSION" ]; then
    echo "[+] Installing archivebox==$ARCHIVEBOX_VERSION..."
    "$ARCHIVEBOX_VENV/bin/pip" install --quiet --upgrade "archivebox==$ARCHIVEBOX_VERSION"
else
    echo "[+] Installing latest archivebox (no version pinned)..."
    "$ARCHIVEBOX_VENV/bin/pip" install --quiet --upgrade archivebox
fi

echo "[√] ArchiveBox installed successfully."
echo "    Run 'archivebox version' to verify."
