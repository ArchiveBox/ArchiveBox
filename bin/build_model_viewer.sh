#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
asset_dir="$repo_dir/archivebox/templates/static/model-viewer"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
npm install --prefix "$build_dir" --no-save --package-lock=false --ignore-scripts three@0.186.0 esbuild@0.27.4 fflate@0.8.2
cp "$asset_dir/three-entry.js" "$build_dir/entry.js"
"$build_dir/node_modules/.bin/esbuild" "$build_dir/entry.js" --bundle --minify --format=esm --target=es2022 --legal-comments=eof --outfile="$asset_dir/three.bundle.js"
cp "$build_dir/node_modules/three/LICENSE" "$asset_dir/LICENSE.three.txt"
cp "$build_dir/node_modules/fflate/LICENSE" "$asset_dir/LICENSE.fflate.txt"
