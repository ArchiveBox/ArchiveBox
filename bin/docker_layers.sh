#!/usr/bin/env bash

# This script takes a single Docker image tag (e.g. "ubuntu:latest") as input
# and shows the contents of the filesystem for each layer in the image.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <image_tag>"
    exit 1
fi

IMAGE=$1
# TMPDIR=$(mktemp -d) 
mkdir -p "$PWD/tmp"
TMPDIR="$PWD/tmp"

# Save the Docker image to a tar archive
echo "Saving Docker image '$IMAGE'..."
if ! docker save "$IMAGE" | pv > "${TMPDIR}/image.tar"; then
    echo "Failed to save image '$IMAGE'. Make sure the image exists and Docker is running."
    rm -rf "${TMPDIR}"
    exit 1
fi

cd "${TMPDIR}" || exit 1

# Extract the top-level metadata of the image tar
echo "Extracting image metadata..."
pwd
tar -xzf image.tar
chmod -R 777 .
cd blobs/sha256 || exit 1

# Typically, the saved image will contain multiple directories each representing a layer.
# Each layer directory should have a 'layer.tar' file that contains the filesystem for that layer.
for LAYERFILE in ./*; do
    if [ -f "${LAYERFILE}" ]; then
        mv "${LAYERFILE}" "${LAYERFILE}.tar"
        tar -xzf "${LAYERFILE}.tar"
        rm "${LAYERFILE}.tar"
        echo "-----------------------------------------------------------------"
        echo "Contents of layer: ${LAYERFILE%/}"
        echo "-----------------------------------------------------------------"
        # List the files in the layer.tar without extracting
        tree -L 2
        echo
    fi
done
