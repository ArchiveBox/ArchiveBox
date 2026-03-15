#!/bin/bash
# postinstall script for archivebox .deb package
set -e

# Create archivebox system user if it doesn't exist
if ! id -u archivebox >/dev/null 2>&1; then
    useradd --system --shell /bin/bash --home-dir /var/lib/archivebox --create-home archivebox
    echo "[+] Created archivebox system user"
fi

# Ensure data directory exists and is owned by archivebox
mkdir -p /var/lib/archivebox
chown archivebox:archivebox /var/lib/archivebox

# Run the virtualenv install script, pinning to the .deb package version
ARCHIVEBOX_VERSION="$(dpkg-query -W -f='${Version}' archivebox 2>/dev/null || echo '')"
export ARCHIVEBOX_VERSION
/opt/archivebox/install.sh

# Reload systemd to pick up the service file (skip if systemd is not running)
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload

    # On upgrade: restart the service if it was enabled (prerm stopped it)
    if [ "$1" = "configure" ] && systemctl is-enabled archivebox >/dev/null 2>&1; then
        systemctl start archivebox 2>/dev/null || true
        echo "[+] Restarted archivebox service after upgrade"
    else
        echo "[i] To start ArchiveBox: sudo systemctl start archivebox"
        echo "[i] To enable on boot:   sudo systemctl enable archivebox"
    fi
fi
