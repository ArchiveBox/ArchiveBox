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


CURRENT_PLAFORM="$(uname)"
REQUIRED_PLATFORM="Darwin"
if [[ "$CURRENT_PLAFORM" != "$REQUIRED_PLATFORM" ]]; then
   echo "[!] Skipping the Homebrew package build on $CURRENT_PLAFORM (it can only be run on $REQUIRED_PLATFORM)."
   exit 0
fi


cd "$REPO_DIR/brew_dist"
# make sure archivebox.rb is up-to-date with the dependencies
git pull
git status | grep 'up to date'

echo
echo "[+] Uninstalling any exisitng archivebox versions..."
brew uninstall archivebox || true
brew untap archivebox/archivebox || true

# echo "[*] Running Formula linters and test build..."
# brew test-bot --tap=ArchiveBox/homebrew-archivebox archivebox/archivebox/archivebox || true
# brew uninstall archivebox || true
# brew untap archivebox/archivebox || true

echo
echo "[+] Installing and building hombrew bottle from https://Github.com/ArchiveBox/homebrew-archivebox#main"
brew tap archivebox/archivebox
brew install --build-bottle archivebox
brew bottle archivebox

echo
echo "[√] Finished. Make sure to commit the outputted .tar.gz and bottle files!"