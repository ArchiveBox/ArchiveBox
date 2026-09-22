#!/usr/bin/env bash

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${LIB_DIR:-$HOME/.config/archivebox/lib}}"
ABXPKG_SPEC="$(UV_LOCK_PATH="$REPO_DIR/uv.lock" uv run --no-cache --no-project python -c 'import os, tomllib; package = next(item for item in tomllib.load(open(os.environ["UV_LOCK_PATH"], "rb"))["package"] if item["name"] == "abxpkg"); wheel = package["wheels"][0]; print("abxpkg @ {}#{}".format(wheel["url"], wheel["hash"].replace(":", "=")))')"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-cache --no-project --with "$ABXPKG_SPEC" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$REPO_DIR/.github/configs/ci-tooling.json:docker_debug_binaries" \
    >/dev/null
DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/docker"
PV_BINARY="$ABXPKG_LIB_DIR/env/bin/pv"
TAR_BINARY="$ABXPKG_LIB_DIR/env/bin/tar"
TREE_BINARY="$ABXPKG_LIB_DIR/env/bin/tree"
test -x "$DOCKER_BINARY"
test -x "$PV_BINARY"
test -x "$TAR_BINARY"
test -x "$TREE_BINARY"

# This script takes a single Docker image tag (e.g. "ubuntu:latest") as input
# and shows the contents of the filesystem for each layer in the image.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <image_tag>"
    exit 1
fi

IMAGE=$1
mkdir -p "$PWD/tmp"
TMPDIR="$PWD/tmp"

# Save the Docker image to a tar archive
echo "Saving Docker image '$IMAGE'..."
if ! "$DOCKER_BINARY" save "$IMAGE" | "$PV_BINARY" > "${TMPDIR}/image.tar"; then
    echo "Failed to save image '$IMAGE'. Make sure the image exists and Docker is running."
    rm -rf "${TMPDIR}"
    exit 1
fi

cd "${TMPDIR}" || exit 1

# Extract the top-level metadata of the image tar
echo "Extracting image metadata..."
pwd
"$TAR_BINARY" -xf image.tar
chmod -R 777 .
cd blobs/sha256 || exit 1

# Typically, the saved image will contain multiple directories each representing a layer.
# Each layer directory should have a 'layer.tar' file that contains the filesystem for that layer.
for LAYERFILE in ./*; do
    if [ -f "${LAYERFILE}" ]; then
        mv "${LAYERFILE}" "${LAYERFILE}.tar"
        mkdir -p "${LAYERFILE}"
        "$TAR_BINARY" -xf "${LAYERFILE}.tar" -C "${LAYERFILE}"
        rm "${LAYERFILE}.tar"
        echo "-----------------------------------------------------------------"
        echo "Contents of layer: ${LAYERFILE%/}"
        echo "-----------------------------------------------------------------"
        # List the files in the layer.tar without extracting
        "$TREE_BINARY" -L 2 "${LAYERFILE}"
        echo
    fi
done
