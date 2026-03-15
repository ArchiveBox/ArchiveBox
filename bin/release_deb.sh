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

echo "[+] Releasing .deb package for archivebox==${VERSION}..."

DEB_FILE="$(ls -1 "$REPO_DIR/dist/"archivebox*.deb 2>/dev/null | head -1)"
if [ -z "$DEB_FILE" ]; then
    echo "[!] No .deb file found in dist/. Run ./bin/build_deb.sh first."
    exit 1
fi

echo "[+] Uploading $DEB_FILE to GitHub Release v${VERSION}..."
gh release upload "v${VERSION}" "$DEB_FILE" --clobber 2>/dev/null || \
    gh release create "v${VERSION}" "$DEB_FILE" --title "v${VERSION}" --generate-notes

echo "[√] .deb package uploaded to GitHub Release v${VERSION}"
echo "    Users can install with:"
echo "      curl -fsSL https://github.com/ArchiveBox/ArchiveBox/releases/download/v${VERSION}/archivebox_${VERSION}_amd64.deb -o /tmp/archivebox.deb"
echo "      sudo apt install /tmp/archivebox.deb"
