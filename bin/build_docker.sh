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
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
cd "$REPO_DIR"


echo "[+] Building docker image in the background..."
docker build . -t archivebox \
               -t archivebox:latest \
               -t archivebox:$VERSION \
               -t docker.io/nikisweeting/archivebox:latest \
               -t docker.io/nikisweeting/archivebox:$VERSION \
               -t docker.io/archivebox/archivebox:latest \
               -t docker.io/archivebox/archivebox:$VERSION \
               -t docker.pkg.github.com/pirate/archivebox/archivebox:latest \
               -t docker.pkg.github.com/pirate/archivebox/archivebox:$VERSION
