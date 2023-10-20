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
which docker > /dev/null || exit 1


TAG_NAME="dev"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
REQUIRED_PLATFORMS=('linux/arm64','linux/amd64','linux/arm/v8','linux/arm/v7')

function check_platforms() {
    INSTALLED_PLATFORMS="$(docker buildx inspect | grep 'Platforms:' )"

    for REQUIRED_PLATFORM in ${REQUIRED_PLATFORMS//,/$IFS}; do
        echo "[+] Checking for: $REQUIRED_PLATFORM..."
        if ! (echo "$INSTALLED_PLATFORMS" | grep -q "$REQUIRED_PLATFORM"); then
            return 1
        fi
    done
    echo
    return 0
}

function create_builder() {
    echo "[+] Creating new xbuilder for: $REQUIRED_PLATFORMS"
    echo

    # Switch to buildx builder if already present / previously created
    docker buildx create --name xbuilder --driver docker-container --bootstrap --use --platform "$REQUIRED_PLATFORMS" || true
    docker buildx inspect --bootstrap || true

    echo
}

function recreate_builder() {
    # Install QEMU binaries for cross-platform building if not installed
    docker run --privileged --rm 'tonistiigi/binfmt' --install all

    # remove existing xbuilder
    docker buildx stop xbuilder || true
    docker buildx rm xbuilder || true

    # Create Docker builder for cross-platform building
    docker buildx use xbuilder && return 0

    create_builder
}


# Check if docker is ready for cross-plaform builds, if not, recreate builder
docker buildx use xbuilder || create_builder
check_platforms || (recreate_builder && check_platforms) || exit 1


echo "[+] Building archivebox:$VERSION docker image..."
# docker builder prune
# docker build . --no-cache -t archivebox-dev \
docker buildx build --platform "$REQUIRED_PLATFORMS" --load . \
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
