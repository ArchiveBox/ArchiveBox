#!/usr/bin/env bash
# ./bin/build_docker.sh dev 'linux/arm/v7'

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
which jq > /dev/null || exit 1
# which pdm > /dev/null || exit 1

SUPPORTED_PLATFORMS="linux/amd64,linux/arm64,linux/arm/v7"

TAG_NAME="${1:-$(git rev-parse --abbrev-ref HEAD)}"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
SELECTED_PLATFORMS="${2:-$SUPPORTED_PLATFORMS}"

echo "[+] Building Docker image: tag=$TAG_NAME version=$SHORT_VERSION arch=$SELECTED_PLATFORMS"

function check_platforms() {
    INSTALLED_PLATFORMS="$(docker buildx inspect | grep 'Platforms:' )"

    for REQUIRED_PLATFORM in ${SELECTED_PLATFORMS//,/$IFS}; do
        echo "[+] Checking for: $REQUIRED_PLATFORM..."
        if ! (echo "$INSTALLED_PLATFORMS" | grep -q "$REQUIRED_PLATFORM"); then
            return 1
        fi
    done
    echo
    return 0
}

function remove_builder() {
    # remove existing xbuilder
    docker buildx stop xbuilder || true
    docker buildx rm xbuilder || true
}

function create_builder() {
    docker buildx use xbuilder && return 0
    echo "[+] Creating new xbuilder for: $SELECTED_PLATFORMS"
    echo

    # Switch to buildx builder if already present / previously created
    docker buildx create --name xbuilder --driver docker-container --bootstrap --use --platform "$SELECTED_PLATFORMS" || true
    docker buildx inspect --bootstrap || true
}

function recreate_builder() {
    # Install QEMU binaries for cross-platform building if not installed
    docker run --privileged --rm 'tonistiigi/binfmt' --install all

    remove_builder
    create_builder
}

# Check if docker is ready for cross-plaform builds, if not, recreate builder
docker buildx use xbuilder 2>&1 >/dev/null || create_builder
check_platforms || (recreate_builder && check_platforms) || exit 1


# Build python package lists
echo "[+] Generating requirements.txt and pdm.lock from pyproject.toml..."
pdm lock --group=':all' --strategy="cross_platform" --production
pdm export --group=':all' --production --without-hashes -o requirements.txt

echo "[+] Building archivebox:$VERSION docker image..."
# docker builder prune
# docker build . --no-cache -t archivebox-dev \
# replace --load with --push to deploy
docker buildx build --platform "$SELECTED_PLATFORMS" --load . \
               -t archivebox/archivebox \
               -t archivebox/archivebox:$TAG_NAME \
               -t archivebox/archivebox:$VERSION \
               -t archivebox/archivebox:$SHORT_VERSION \
               -t archivebox/archivebox:latest \
               -t nikisweeting/archivebox \
               -t nikisweeting/archivebox:$TAG_NAME \
               -t nikisweeting/archivebox:$VERSION \
               -t nikisweeting/archivebox:$SHORT_VERSION \
               -t nikisweeting/archivebox:latest \
               -t ghcr.io/archivebox/archivebox/archivebox:$TAG_NAME \
               -t ghcr.io/archivebox/archivebox/archivebox:$VERSION \
               -t ghcr.io/archivebox/archivebox/archivebox:$SHORT_VERSION
