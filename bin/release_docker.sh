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

SUPPORTED_PLATFORMS="linux/amd64,linux/arm64,linux/arm/v7"

TAG_NAME="${1:-$(git rev-parse --abbrev-ref HEAD)}"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
SELECTED_PLATFORMS="${2:-$SUPPORTED_PLATFORMS}"


# echo "[*] Logging in to Docker Hub & Github Container Registry"
# docker login --username=nikisweeting
# docker login ghcr.io --username=pirate

echo "[^] Building docker image"
./bin/build_docker.sh "$TAG_NAME" "$SELECTED_PLATFORMS"

echo "[^] Uploading docker image"
docker buildx build --platform "$SELECTED_PLATFORMS" --push . \
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