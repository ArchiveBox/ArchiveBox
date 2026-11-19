#!/usr/bin/env bash
set -euo pipefail
# Called only on disposable official Ubuntu runner images, not developer hosts.
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted ||
      "${RUNNER_OS:-}" != Linux || "${RUNNER_ARCH:-}" != X64 ]]; then
  exit 0
fi
. /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_CODENAME" != noble ]]; then
  exit 0
fi
package=fonts-wqy-zenhei_0.9.45-8_all.deb
# Ubuntu's signed noble/universe/binary-amd64/Packages record.
checksum=496969d65dc5664a3291e678d5cbef6815dc308ee5bf37b656c00af2cb490410
archive_dir="$RUNNER_TEMP/noble-font-archive"
archive="$archive_dir/$package"
mkdir -p "$archive_dir"
exec 9>"$RUNNER_TEMP/noble-font-stage.lock"
flock 9
if [[ "${1:-}" == --lazy ]] &&
   [[ "$(dpkg-query -W -f='${db:Status-Status}' fonts-wqy-zenhei 2>/dev/null)" == installed ]]; then
  exit 0
fi
if [[ ! -f "$archive" ]]; then
  temp="$(mktemp "$archive_dir/download.XXXXXX")"
  trap 'rm -f -- "$temp"' EXIT
  if ! curl --fail --silent --show-error --max-time 45 \
    "https://mirrors.edge.kernel.org/ubuntu/pool/universe/f/fonts-wqy-zenhei/$package" \
    --output "$temp"; then
    echo '::warning::Font archive prefetch unavailable; APT will acquire its own package.'
    exit 0
  fi
  printf '%s  %s\n' "$checksum" "$temp" | sha256sum --check --strict
  mv "$temp" "$archive"
fi
printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --strict
if ! cmp -s "$archive" "/var/cache/apt/archives/$package"; then
  sudo install -m 0644 "$archive" "/var/cache/apt/archives/$package"
fi
if [[ "${1:-}" != --lazy ]]; then
  echo 'verified=true' >> "$GITHUB_OUTPUT"
fi
