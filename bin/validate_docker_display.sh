#!/usr/bin/env bash
# Real Compose regression checks. Build the image under test first, then run:
# IMAGE=archivebox/archivebox:issue-1872 ./bin/validate_docker_display.sh
set -Eeuo pipefail

export IMAGE="${IMAGE:-archivebox/archivebox:dev}"
validation_dir="$(mktemp -d "${TMPDIR:-/tmp}/archivebox-display.XXXXXX")"
compose=(docker compose --project-name "archivebox-display-$$" --file "$validation_dir/compose.yml")
cleanup() {
    "${compose[@]}" down --volumes --remove-orphans
    echo "Validation files: $validation_dir"
}
trap cleanup EXIT

cat > "$validation_dir/compose.yml" <<'YAML'
services:
  archivebox:
    image: ${IMAGE}
    volumes:
      - ./data:/data
      - tmp:/tmp/archivebox
    shm_size: 1gb
  novnc:
    image: theasp/novnc:latest
    environment:
      DISPLAY_WIDTH: 1280
      DISPLAY_HEIGHT: 800
      RUN_XTERM: "no"
    healthcheck:
      test: ["CMD", "xdpyinfo", "-display", ":0"]
      interval: 2s
      timeout: 2s
      retries: 10
volumes:
  tmp:
YAML

"${compose[@]}" up -d --wait novnc

# Check the real runtime dependency as well as successful X11 connectivity.
"${compose[@]}" run --rm archivebox sh -ec '
    command -v xdpyinfo
    test "$DISPLAY" = novnc:0.0
    xdpyinfo >/dev/null
'
"${compose[@]}" run --rm -e DISPLAY=novnc:0.0 archivebox sh -ec '
    test "$DISPLAY" = novnc:0.0
    xdpyinfo >/dev/null
'

# Explicit values belong to the caller, even when X11 is unavailable.
"${compose[@]}" run --rm -e DISPLAY=unavailable:0 archivebox sh -ec '
    test "$DISPLAY" = unavailable:0
'
# An explicit empty value disables automatic display discovery.
"${compose[@]}" run --rm -e DISPLAY= archivebox sh -ec '
    test "${DISPLAY+x}" = x
    test -z "$DISPLAY"
'

"${compose[@]}" stop novnc
"${compose[@]}" run --rm archivebox sh -ec '
    test "${DISPLAY+x}" != x
'
"${compose[@]}" run --rm -e DISPLAY=novnc:0.0 archivebox sh -ec '
    test "$DISPLAY" = novnc:0.0
'
echo 'PASS: Compose DISPLAY discovery, explicit override, empty opt-out, and headless fallback'
