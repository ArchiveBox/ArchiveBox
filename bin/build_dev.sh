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


TAG_NAME="${1:-$(git rev-parse --abbrev-ref HEAD)}"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
REQUIRED_PLATFORMS="${2:-"linux/arm64,linux/amd64,linux/arm/v7"}"


# Build python package lists
# https://pdm-project.org/latest/usage/lockfile/
echo "[+] Generating requirements.txt and pdm.lock from pyproject.toml..."
pdm lock --group=':all' --production --lockfile pdm.lock --strategy="cross_platform"
pdm sync --group=':all' --production --lockfile pdm.lock --clean || pdm sync --group=':all' --production --lockfile pdm.lock --clean
pdm export --group=':all' --production --lockfile pdm.lock --without-hashes -o requirements.txt

pdm lock --group=':all' --dev --lockfile pdm.dev.lock --strategy="cross_platform" 
pdm sync --group=':all' --dev --lockfile pdm.dev.lock --clean || pdm sync --group=':all' --dev --lockfile pdm.dev.lock --clean
pdm export --group=':all' --dev --lockfile pdm.dev.lock --without-hashes -o requirements-dev.txt



echo "[+] Building Docker image: tag=$TAG_NAME version=$SHORT_VERSION arch=$REQUIRED_PLATFORMS"


echo "[+] Building archivebox:$VERSION docker image..."
# docker builder prune
docker build . --no-cache -t archivebox-dev --load

# docker buildx build --platform "$REQUIRED_PLATFORMS" --load . \
#                -t archivebox \
#                -t archivebox:$TAG_NAME \
#                -t archivebox:$VERSION \
#                -t archivebox:$SHORT_VERSION
