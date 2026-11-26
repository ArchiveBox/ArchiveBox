#!/usr/bin/env bash
set -euo pipefail

if [[ -r "${CURL_CA_BUNDLE:-}" && -z "${HOMEBREW_CURLRC:-}" ]]; then
  # Homebrew's portable Ruby downloader disables the default curlrc.
  # Give it the same system + CI proxy CA bundle as the rest of the job.
  curlrc="$RUNNER_TEMP/archivebox-homebrew.curlrc"
  printf 'cacert = "%s"\n' "$CURL_CA_BUNDLE" > "$curlrc"
  printf 'HOMEBREW_CURLRC=%s\n' "$curlrc" >> "$GITHUB_ENV"
fi
