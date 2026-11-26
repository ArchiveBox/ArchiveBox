#!/usr/bin/env bash
set -euo pipefail

version="${CHROME_VENDOR_VERSION:?}"
checksum="${CHROME_VENDOR_SHA256:?}"
archive_dir="$RUNNER_TEMP/chrome-vendor-archive"
filename="$version-chrome-linux64.zip"
archive="$archive_dir/$filename"
# Never seed a per-test isolated abxpkg installation.
cache="$RUNNER_TEMP/archivebox-lib/puppeteer/cache/chrome"
browser="$cache/linux-$version/chrome-linux64/chrome"

case "${1:?}" in
  check)
    actual="$("$browser" --version 2>/dev/null || true)"
    if [[ "$actual" != "Google Chrome for Testing $version" ]]; then
      echo 'needed=true' >> "$GITHUB_OUTPUT"
    fi
    ;;
  download)
    mkdir -p "$archive_dir"
    temporary="$(mktemp "$archive_dir/download.XXXXXX")"
    trap 'rm -f -- "$temporary"' EXIT
    curl --fail --location --silent --show-error --max-time 240 \
      "https://storage.googleapis.com/chrome-for-testing-public/$version/linux64/chrome-linux64.zip?generation=${CHROME_VENDOR_GENERATION:?}" \
      --output "$temporary"
    printf '%s  %s\n' "$checksum" "$temporary" | sha256sum --check --strict
    mv "$temporary" "$archive"
    ;;
  stage)
    printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --strict
    mkdir -p "$cache"
    # Puppeteer still extracts the archive and installs system dependencies.
    ln -f "$archive" "$cache/$filename"
    ;;
  *)
    exit 2
    ;;
esac
