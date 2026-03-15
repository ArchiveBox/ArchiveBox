#!/bin/bash
# preremove script for archivebox .deb package
set -e

# Stop the service if running
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl stop archivebox 2>/dev/null || true
    systemctl disable archivebox 2>/dev/null || true
fi

echo "[+] Removing ArchiveBox virtualenv..."
rm -rf /opt/archivebox/venv

echo "[i] Your ArchiveBox data in /var/lib/archivebox has NOT been removed."
echo "    The 'archivebox' system user has NOT been removed."
echo "    Remove them manually if you no longer need them:"
echo "      sudo rm -rf /var/lib/archivebox"
echo "      sudo userdel archivebox"
