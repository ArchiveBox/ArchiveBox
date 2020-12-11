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

echo "[+] Building Homebrew bottle"
brew install --build-bottle ./archivebox.rb
brew bottle archivebox
