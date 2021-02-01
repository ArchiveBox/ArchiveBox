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
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
cd "$REPO_DIR"

which docker > /dev/null

echo "[+] Building archivebox:$VERSION docker image..."
docker build . -t archivebox \
               -t archivebox:latest \
               -t archivebox:$VERSION \
               -t archivebox:$SHORT_VERSION \
               -t docker.io/nikisweeting/archivebox:latest \
               -t docker.io/nikisweeting/archivebox:$VERSION \
               -t docker.io/nikisweeting/archivebox:$SHORT_VERSION \
               -t docker.io/archivebox/archivebox:latest \
               -t docker.io/archivebox/archivebox:$VERSION \
               -t docker.io/archivebox/archivebox:$SHORT_VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:latest \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$SHORT_VERSION
