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
REQUIRED_PLATFORMS="${2:-$SUPPORTED_PLATFORMS}"

echo "[+] Building Docker image: tag=$TAG_NAME version=$SHORT_VERSION arch=$REQUIRED_PLATFORMS"

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

function remove_builder() {
    # remove existing xbuilder
    docker buildx stop xbuilder || true
    docker buildx rm xbuilder || true
}

function create_builder() {
    docker buildx use xbuilder && return 0
    echo "[+] Creating new xbuilder for: $REQUIRED_PLATFORMS"
    echo

    # Switch to buildx builder if already present / previously created
    docker buildx create --name xbuilder --driver docker-container --bootstrap --use --platform "$REQUIRED_PLATFORMS" || true
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
docker buildx build --platform "$REQUIRED_PLATFORMS" --load . \
               -t archivebox \
               -t archivebox:$TAG_NAME \
               -t archivebox:$VERSION \
               -t archivebox:$SHORT_VERSION \
               -t archivebox:latest \
               -t docker.io/nikisweeting/archivebox:$TAG_NAME \
               -t docker.io/nikisweeting/archivebox:$VERSION \
               -t docker.io/nikisweeting/archivebox:$SHORT_VERSION \
               -t docker.io/archivebox/archivebox:$TAG_NAME \
               -t docker.io/archivebox/archivebox:$VERSION \
               -t docker.io/archivebox/archivebox:$SHORT_VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$TAG_NAME \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$VERSION \
               -t docker.pkg.github.com/archivebox/archivebox/archivebox:$SHORT_VERSION
