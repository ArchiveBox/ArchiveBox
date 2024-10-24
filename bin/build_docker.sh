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
IFS=$' '

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
cd "$REPO_DIR"

which docker > /dev/null || exit 1
which jq > /dev/null || exit 1
# which pdm > /dev/null || exit 1

declare -a TAG_NAMES=("$@")
BRANCH_NAME="${1:-$(git rev-parse --abbrev-ref HEAD)}"
VERSION="$(grep '^version = ' "${REPO_DIR}/pyproject.toml" | awk -F'"' '{print $2}')"
GIT_SHA=sha-"$(git rev-parse --short HEAD)"
SELECTED_PLATFORMS="linux/amd64,linux/arm64"

# if not already in TAG_NAMES, add GIT_SHA and BRANCH_NAME  
if ! echo "${TAG_NAMES[@]}" | grep -q "$GIT_SHA"; then
    TAG_NAMES+=("$GIT_SHA")
fi
if ! echo "${TAG_NAMES[@]}" | grep -q "$BRANCH_NAME"; then
    TAG_NAMES+=("$BRANCH_NAME")
fi
if ! echo "${TAG_NAMES[@]}" | grep -q "$VERSION"; then
    TAG_NAMES+=("$VERSION")
fi

echo "[+] Building Docker image for $SELECTED_PLATFORMS: branch=$BRANCH_NAME version=$VERSION tags=${TAG_NAMES[*]}"

declare -a FULL_TAG_NAMES
# for each tag in TAG_NAMES, add archivebox/archivebox:tag and nikisweeting/archivebox:tag to FULL_TAG_NAMES
for TAG_NAME in "${TAG_NAMES[@]}"; do
    [[ "$TAG_NAME" == "" ]] && continue
    FULL_TAG_NAMES+=("-t archivebox/archivebox:$TAG_NAME")
    FULL_TAG_NAMES+=("-t nikisweeting/archivebox:$TAG_NAME")
    FULL_TAG_NAMES+=("-t ghcr.io/archivebox/archivebox:$TAG_NAME")
done
echo "${FULL_TAG_NAMES[@]}"

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
    docker pull 'moby/buildkit:buildx-stable-1'

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
docker buildx use xbuilder >/dev/null 2>&1 || create_builder
check_platforms || (recreate_builder && check_platforms) || exit 1


# Make sure pyproject.toml, pdm{.dev}.lock, requirements{-dev}.txt, package{-lock}.json are all up-to-date
# echo "[!] Make sure you've run ./bin/lock_pkgs.sh recently!"
bash ./bin/lock_pkgs.sh


echo "[+] Building archivebox:$VERSION docker image..."
# docker builder prune
# docker build . --no-cache -t archivebox-dev \
# replace --load with --push to deploy
# shellcheck disable=SC2068
docker buildx build --platform "$SELECTED_PLATFORMS" --load . ${FULL_TAG_NAMES[@]}
