#!/usr/bin/env bash
# ArchiveBox uv install shortcut (macOS/Linux/BSD)
#
# Usage:
#   curl -fsSL 'https://get.archivebox.io' | bash

set -Eeuo pipefail

ARCHIVEBOX_PYTHON="${ARCHIVEBOX_PYTHON:-3.13}"
ARCHIVEBOX_PACKAGE="${ARCHIVEBOX_PACKAGE:-archivebox>=0.9.0rc0,<0.10}"

export PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$HOME/.cargo/bin:$PATH"

UV_BINARY="$(command -v uv || true)"
if [ -z "$UV_BINARY" ]; then
    echo "[+] Installing uv..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "[X] curl or wget is required to install uv." >&2
        exit 1
    fi

    hash -r
    UV_BINARY="$(command -v uv || true)"
fi

if [ -z "$UV_BINARY" ]; then
    echo "[X] uv was installed but is not available on PATH." >&2
    echo "    See https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

echo "[+] Installing ArchiveBox with uv..."
"$UV_BINARY" tool install --python "$ARCHIVEBOX_PYTHON" --prerelease explicit --upgrade "$ARCHIVEBOX_PACKAGE"

cat <<EOF

[+] ArchiveBox is installed. Initialize a collection when you are ready:

    mkdir -p ~/archivebox/data
    cd ~/archivebox/data
    archivebox init
    archivebox install

More install and usage options: https://github.com/ArchiveBox/ArchiveBox/wiki/Install
EOF
