#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

DEPLOY_HOST="${DEPLOY_HOST:-cabbage}"
DEPLOY_PORT="${DEPLOY_PORT:-44}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/archivebox.demo}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-archivebox}"
DEPLOY_IMAGE="${DEPLOY_IMAGE:-archivebox/archivebox:dev}"
DEPLOY_EXPECT_VERSION="${DEPLOY_EXPECT_VERSION:-}"
DEPLOY_ABXPKG_LIB_DIR="${DEPLOY_ABXPKG_LIB_DIR:-}"

ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${LIB_DIR:-$HOME/.config/archivebox/lib}}"
ABXPKG_SPEC="$(UV_LOCK_PATH="$REPO_DIR/uv.lock" uv run --no-cache --no-project python -c 'import os, tomllib; package = next(item for item in tomllib.load(open(os.environ["UV_LOCK_PATH"], "rb"))["package"] if item["name"] == "abxpkg"); wheel = package["wheels"][0]; print("abxpkg @ {}#{}".format(wheel["url"], wheel["hash"].replace(":", "=")))')"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-cache --no-project --with "$ABXPKG_SPEC" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$REPO_DIR/.github/configs/ci-tooling.json:deploy_binaries" \
    >/dev/null
export PATH="$ABXPKG_LIB_DIR/env/bin:$PATH"
GIT_BINARY="$ABXPKG_LIB_DIR/env/bin/git"
SSH_BINARY="$ABXPKG_LIB_DIR/env/bin/ssh"
test -x "$GIT_BINARY"
test -x "$SSH_BINARY"

if [[ "$("$GIT_BINARY" branch --show-current)" != "dev" ]]; then
    echo "[X] Run this from the dev branch." >&2
    exit 1
fi

if [[ -n "$("$GIT_BINARY" status --short)" ]]; then
    echo "[X] Refusing to deploy with a dirty worktree. Commit or stash changes first." >&2
    "$GIT_BINARY" status --short >&2
    exit 1
fi

echo "[+] Pushing dev to GitHub..."
"$GIT_BINARY" push origin dev

if [[ "${SKIP_DEMO:-0}" == "1" ]]; then
    echo "[√] Skipped demo deploy."
    exit 0
fi

echo "[+] Deploying ${DEPLOY_IMAGE} on ${DEPLOY_HOST}:${DEPLOY_PATH}..."
"$SSH_BINARY" -p "$DEPLOY_PORT" "$DEPLOY_HOST" DEPLOY_PATH="$DEPLOY_PATH" DEPLOY_SERVICE="$DEPLOY_SERVICE" DEPLOY_IMAGE="$DEPLOY_IMAGE" DEPLOY_EXPECT_VERSION="$DEPLOY_EXPECT_VERSION" DEPLOY_ABXPKG_LIB_DIR="$DEPLOY_ABXPKG_LIB_DIR" 'bash -s' <<'REMOTE'
set -Eeuo pipefail
cd "$DEPLOY_PATH"
ABXPKG_LIB_DIR="${DEPLOY_ABXPKG_LIB_DIR:-$HOME/.config/archivebox/lib}"
DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/docker"
test -x "$DOCKER_BINARY"

if [[ -f compose.yml ]]; then
    COMPOSE_FILE=compose.yml
elif [[ -f compose.yaml ]]; then
    COMPOSE_FILE=compose.yaml
elif [[ -f docker-compose.yml ]]; then
    COMPOSE_FILE=docker-compose.yml
else
    echo "[X] No compose file found in $DEPLOY_PATH" >&2
    exit 1
fi

cat > .archivebox-deploy.override.yml <<EOF
services:
  $DEPLOY_SERVICE:
    image: $DEPLOY_IMAGE
    user: ""
    entrypoint: null
    command: null
EOF

COMPOSE=("$DOCKER_BINARY" compose -f "$COMPOSE_FILE" -f .archivebox-deploy.override.yml)

echo "[+] Pulling $DEPLOY_IMAGE..."
"${COMPOSE[@]}" pull "$DEPLOY_SERVICE"

echo "[+] Restarting $DEPLOY_SERVICE..."
"${COMPOSE[@]}" up -d "$DEPLOY_SERVICE"

has_argo=0
while IFS= read -r service; do
    [[ "$service" == "argo" ]] && has_argo=1
done < <("${COMPOSE[@]}" config --services)
if [[ "$has_argo" == "1" ]]; then
    echo "[+] Ensuring argo tunnel is running..."
    "${COMPOSE[@]}" up -d argo
fi

echo "[+] Container status:"
"${COMPOSE[@]}" ps "$DEPLOY_SERVICE"
if [[ "$has_argo" == "1" ]]; then
    "${COMPOSE[@]}" ps argo
fi

echo "[+] ArchiveBox version:"
VERSION_OUTPUT="$("${COMPOSE[@]}" exec -T "$DEPLOY_SERVICE" archivebox version </dev/null 2>&1 || true)"
line_count=0
while IFS= read -r line && [[ "$line_count" -lt 40 ]]; do
    printf '%s\n' "$line"
    line_count=$((line_count + 1))
done <<<"$VERSION_OUTPUT"
if [[ -n "$DEPLOY_EXPECT_VERSION" && "$VERSION_OUTPUT" != *"ArchiveBox v${DEPLOY_EXPECT_VERSION}"* ]]; then
    echo "[X] Deployed container is not running ArchiveBox ${DEPLOY_EXPECT_VERSION}" >&2
    exit 1
fi

echo "[+] Health check:"
"${COMPOSE[@]}" exec -T "$DEPLOY_SERVICE" /opt/archivebox/lib/env/bin/curl -fsS --max-time 10 --connect-timeout 2 -H 'Host: admin.archivebox.io' http://127.0.0.1:8000/health/ </dev/null
REMOTE

echo "[√] Demo deploy finished."
