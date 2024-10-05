#!/usr/bin/env bash

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

declare -a TAG_NAMES="$*"
BRANCH_NAME="${1:-$(git rev-parse --abbrev-ref HEAD)}"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
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

echo "[+] Building + releasing Docker image for $SELECTED_PLATFORMS: branch=$BRANCH_NAME version=$VERSION tags=${TAG_NAMES[*]}"

declare -a FULL_TAG_NAMES
# for each tag in TAG_NAMES, add archivebox/archivebox:tag and nikisweeting/archivebox:tag to FULL_TAG_NAMES
for TAG_NAME in "${TAG_NAMES[@]}"; do
    [[ "$TAG_NAME" == "" ]] && continue
    FULL_TAG_NAMES+=("-t archivebox/archivebox:$TAG_NAME")
    FULL_TAG_NAMES+=("-t nikisweeting/archivebox:$TAG_NAME")
    FULL_TAG_NAMES+=("-t ghcr.io/archivebox/archivebox:$TAG_NAME")
done
echo "${FULL_TAG_NAMES[@]}"


./bin/lock_pkgs.sh

# echo "[*] Logging in to Docker Hub & Github Container Registry"
# docker login --username=nikisweeting
# docker login ghcr.io --username=pirate

echo "[^] Uploading docker image"
# shellcheck disable=SC2068
docker buildx build --platform "$SELECTED_PLATFORMS" --push . ${FULL_TAG_NAMES[@]}   
