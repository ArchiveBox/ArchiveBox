#!/usr/bin/env bash

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
set -o errexit
set -o errtrace
set -o nounset
set -o pipefail
IFS=$' '

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
cd "$REPO_DIR"

ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${LIB_DIR:-$HOME/.config/archivebox/lib}}"
locked_abxpkg_version() {
    local line package=""
    while IFS= read -r line; do
        case "$line" in
            '[[package]]') package="" ;;
            'name = "abxpkg"') package="abxpkg" ;;
            'version = "'*'"')
                [[ "$package" == "abxpkg" ]] || continue
                line="${line#version = \"}"
                printf '%s\n' "${line%\"}"
                return 0
                ;;
        esac
    done < "$REPO_DIR/uv.lock"
    return 1
}
ABXPKG_VERSION="$(locked_abxpkg_version)"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-project --with "abxpkg==$ABXPKG_VERSION" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$REPO_DIR/.github/configs/ci-tooling.json:docker_binaries" \
    >/dev/null
DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/docker"
GIT_BINARY="$ABXPKG_LIB_DIR/env/bin/git"
PYTHON_BINARY="$ABXPKG_LIB_DIR/env/bin/python"
test -x "$DOCKER_BINARY"
test -x "$GIT_BINARY"
test -x "$PYTHON_BINARY"

declare -a TAG_NAMES=("$@")
BRANCH_NAME="${1:-$("$GIT_BINARY" rev-parse --abbrev-ref HEAD)}"
VERSION="$("$PYTHON_BINARY" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
GIT_SHA=sha-"$("$GIT_BINARY" rev-parse --short HEAD)"
SELECTED_PLATFORMS="${DOCKER_PLATFORMS:-${SELECTED_PLATFORMS:-linux/amd64,linux/arm64}}"
DOCKER_IMAGE_REPOS="${DOCKER_IMAGE_REPOS:-archivebox/archivebox ghcr.io/archivebox/archivebox}"
ABX_DL_VERSION="$("$PYTHON_BINARY" -c 'import tomllib; lock=tomllib.load(open("uv.lock", "rb")); print(next(pkg["version"] for pkg in lock["package"] if pkg["name"] == "abx-dl"))')"
test -n "$ABX_DL_VERSION"
ABX_DL_IMAGE="${ABX_DL_IMAGE:-archivebox/abx-dl:${ABX_DL_VERSION}}"

contains_tag() {
    local candidate="$1" tag
    for tag in "${TAG_NAMES[@]}"; do
        [[ "$tag" == "$candidate" ]] && return 0
    done
    return 1
}

if ! contains_tag "$GIT_SHA"; then
   TAG_NAMES+=("$GIT_SHA")
fi
if ! contains_tag "$BRANCH_NAME"; then
   TAG_NAMES+=("$BRANCH_NAME")
fi
if ! contains_tag "$VERSION"; then
   TAG_NAMES+=("$VERSION")
fi

echo "[+] Building + releasing Docker image for $SELECTED_PLATFORMS: branch=$BRANCH_NAME version=$VERSION abx_dl_image=$ABX_DL_IMAGE tags=${TAG_NAMES[*]}"

declare -a FULL_TAG_NAMES
for TAG_NAME in "${TAG_NAMES[@]}"; do
    [[ "$TAG_NAME" == "" ]] && continue
    for IMAGE_REPO in $DOCKER_IMAGE_REPOS; do
        FULL_TAG_NAMES+=("-t" "$IMAGE_REPO:$TAG_NAME")
    done
done
echo "${FULL_TAG_NAMES[@]}"

function check_platforms() {
    INSTALLED_PLATFORMS="$("$DOCKER_BINARY" buildx inspect)"

    for REQUIRED_PLATFORM in ${SELECTED_PLATFORMS//,/$IFS}; do
        echo "[+] Checking for: $REQUIRED_PLATFORM..."
        if [[ "$INSTALLED_PLATFORMS" != *"$REQUIRED_PLATFORM"* ]]; then
            return 1
        fi
    done
    echo
    return 0
}

function remove_builder() {
    "$DOCKER_BINARY" buildx stop xbuilder
    "$DOCKER_BINARY" buildx rm xbuilder
}

function create_builder() {
    "$DOCKER_BINARY" buildx use xbuilder && return 0
    echo "[+] Creating new xbuilder for: $SELECTED_PLATFORMS"
    echo
    "$DOCKER_BINARY" pull 'moby/buildkit:buildx-stable-1'
    "$DOCKER_BINARY" buildx create --name xbuilder --driver docker-container --bootstrap --use --platform "$SELECTED_PLATFORMS"
    "$DOCKER_BINARY" buildx inspect --bootstrap
}

function recreate_builder() {
    "$DOCKER_BINARY" run --privileged --rm 'tonistiigi/binfmt' --install all

    remove_builder
    create_builder
}

"$DOCKER_BINARY" buildx use xbuilder >/dev/null 2>&1 || create_builder
check_platforms || (recreate_builder && check_platforms) || exit 1

echo "[^] Uploading docker image"
mkdir -p "$HOME/.cache/docker/archivebox"
"$DOCKER_BINARY" buildx imagetools inspect "$ABX_DL_IMAGE"

"$DOCKER_BINARY" buildx build \
   --platform "$SELECTED_PLATFORMS" \
   --pull \
   --build-arg "ABX_DL_IMAGE=$ABX_DL_IMAGE" \
   --cache-from type=local,src="$HOME/.cache/docker/archivebox" \
   --cache-to type=local,compression=zstd,mode=min,oci-mediatypes=true,dest="$HOME/.cache/docker/archivebox" \
   --push . "${FULL_TAG_NAMES[@]}"

echo "[^] Verifying pushed Docker manifests include: $SELECTED_PLATFORMS"
for TAG_NAME in "${TAG_NAMES[@]}"; do
    [[ "$TAG_NAME" == "" ]] && continue
    for IMAGE_REPO in $DOCKER_IMAGE_REPOS; do
        MANIFEST="$("$DOCKER_BINARY" buildx imagetools inspect "$IMAGE_REPO:$TAG_NAME")"
        for REQUIRED_PLATFORM in ${SELECTED_PLATFORMS//,/$IFS}; do
            if [[ "$MANIFEST" != *"Platform:    $REQUIRED_PLATFORM"* ]]; then
                echo "[X] $IMAGE_REPO:$TAG_NAME is missing platform: $REQUIRED_PLATFORM" >&2
                echo "$MANIFEST" >&2
                exit 1
            fi
        done
    done
done
echo "[√] Docker manifests include all requested platforms."
