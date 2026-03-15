#!/bin/bash
# preremove script for archivebox .deb package
set -e

# dpkg passes "$1" as "remove", "purge", or "upgrade".

# Always stop the service before removing or upgrading, because postinstall
# replaces the venv in-place — the running process would use stale binaries.
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl stop archivebox 2>/dev/null || true
fi

# Only disable + clean up on full removal, not during upgrade.
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl disable archivebox 2>/dev/null || true
    fi

    echo "[+] Removing ArchiveBox virtualenv..."
    rm -rf /opt/archivebox/venv

    echo "[i] Your ArchiveBox data in /var/lib/archivebox has NOT been removed."
    echo "    The 'archivebox' system user has NOT been removed."
    echo "    Remove them manually if you no longer need them:"
    echo "      sudo rm -rf /var/lib/archivebox"
    echo "      sudo userdel archivebox"
fi
