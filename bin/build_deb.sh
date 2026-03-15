#!/usr/bin/env bash

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# set -o xtrace
set -o errexit
set -o errtrace
set -o nounset
set -o pipefail
IFS=$'\n'

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
cd "$REPO_DIR"

VERSION="$(grep '^version = ' "${REPO_DIR}/pyproject.toml" | awk -F'"' '{print $2}')"
export VERSION

# Default to amd64, can be overridden with ARCH=arm64
export ARCH="${ARCH:-amd64}"

echo "[+] Building .deb package for archivebox_${VERSION}_${ARCH}..."

# Check for nfpm
if ! command -v nfpm &>/dev/null; then
    echo "[!] nfpm not found. Install it with one of:"
    echo "    go install github.com/goreleaser/nfpm/v2/cmd/nfpm@latest"
    echo "    uv tool install nfpm"
    echo "    brew install goreleaser/tap/nfpm"
    echo "    curl -sfL https://install.goreleaser.com/github.com/goreleaser/nfpm.sh | sh"
    exit 1
fi

mkdir -p "$REPO_DIR/dist"

nfpm package \
    --config "$REPO_DIR/pkg/debian/nfpm.yaml" \
    --packager deb \
    --target "$REPO_DIR/dist/"

echo
echo "[√] Built .deb package:"
ls -la "$REPO_DIR/dist/"archivebox*.deb
