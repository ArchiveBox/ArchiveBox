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
TAG_NAME="dev"
cd "$REPO_DIR"

which docker > /dev/null


# Install QEMU binaries for cross-platform building
docker run --privileged --rm tonistiigi/binfmt --install all || true

# Create Docker builder for cross-platform building
docker buildx use xbuilder || docker buildx create --name xbuilder --driver docker-container --bootstrap --use

# Verify that amd64 and arm64 support are all present
docker buildx inspect | grep 'amd64.*arm64' || exit 1


echo "[+] Building archivebox:$VERSION docker image..."
#docker build . \
docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 --push . \
               -t archivebox \
               -t archivebox:$TAG_NAME \
               -t archivebox:$VERSION \
               -t archivebox:$SHORT_VERSION \
               -t docker.io/nikisweeting/archivebox:$TAG_NAME \
               -t docker.io/nikisweeting/archivebox:$VERSION \
               -t docker.io/nikisweeting/archivebox:$SHORT_VERSION \
               -t docker.io/archivebox/archivebox:$TAG_NAME \
               -t docker.io/archivebox/archivebox:$VERSION \
               -t docker.io/archivebox/archivebox:$SHORT_VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$TAG_NAME \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$SHORT_VERSION
