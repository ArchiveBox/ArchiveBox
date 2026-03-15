#!/bin/bash
# preremove script for archivebox .deb package
set -e

echo "[+] Removing ArchiveBox virtualenv..."
rm -rf /opt/archivebox/venv

echo "[i] Your ArchiveBox data directories have NOT been removed."
echo "    Remove them manually if you no longer need them."
