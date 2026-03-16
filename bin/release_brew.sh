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
FORMULA_FILE="$REPO_DIR/brew_dist/archivebox.rb"
TAP_REPO="ArchiveBox/homebrew-archivebox"

if [ ! -f "$FORMULA_FILE" ]; then
    echo "[!] Formula not found at $FORMULA_FILE"
    echo "    Run ./bin/build_brew.sh first to generate it."
    exit 1
fi

echo "[+] Releasing Homebrew formula for archivebox==${VERSION} to ${TAP_REPO}..."

# Clone the tap repo, update formula, commit, and push
TMPDIR="$(mktemp -d)"
trap "rm -rf $TMPDIR" EXIT

git clone "https://github.com/${TAP_REPO}.git" "$TMPDIR/tap"
cp "$FORMULA_FILE" "$TMPDIR/tap/archivebox.rb"

cd "$TMPDIR/tap"
git add archivebox.rb
if git diff --cached --quiet; then
    echo "[i] No changes to formula, skipping release."
    exit 0
fi

git commit -m "Update archivebox to v${VERSION}"
git push origin HEAD

echo "[√] Homebrew formula pushed to ${TAP_REPO}"
echo "    Users can install with:"
echo "      brew tap archivebox/archivebox"
echo "      brew install archivebox"
