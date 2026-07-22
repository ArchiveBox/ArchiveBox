#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

DEPLOY_PATH="${DEPLOY_PATH:-/opt/archivebox.demo}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-archivebox}"
DEPLOY_IMAGE="${DEPLOY_IMAGE:-archivebox/archivebox:dev}"
DEPLOY_INTERVAL="${DEPLOY_INTERVAL:-60}"
STATE_FILE="${STATE_FILE:-${DEPLOY_PATH}/.archivebox-dev-image.digest}"
OVERRIDE_FILE="${OVERRIDE_FILE:-${DEPLOY_PATH}/.archivebox-deploy.override.yml}"
ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-$HOME/.config/archivebox/lib}"
DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/docker"
test -x "$DOCKER_BINARY"

cd "$DEPLOY_PATH"

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

cat > "$OVERRIDE_FILE" <<EOF
services:
  $DEPLOY_SERVICE:
    image: $DEPLOY_IMAGE
    user: ""
    entrypoint: null
    command: null
EOF

COMPOSE=("$DOCKER_BINARY" compose -f "$COMPOSE_FILE" -f "$OVERRIDE_FILE")

remote_digest() {
    local line
    while IFS= read -r line; do
        if [[ "$line" == "Digest:"* ]]; then
            line="${line#Digest:}"
            line="${line#"${line%%[![:space:]]*}"}"
            printf '%s\n' "$line"
            return 0
        fi
    done < <("$DOCKER_BINARY" buildx imagetools inspect "$DEPLOY_IMAGE")
    return 1
}

deploy_digest() {
    local digest="$1"

    echo "[+] Deploying ${DEPLOY_IMAGE}@${digest}"
    "${COMPOSE[@]}" pull "$DEPLOY_SERVICE"
    "${COMPOSE[@]}" up -d "$DEPLOY_SERVICE"

    local has_argo=0 service
    while IFS= read -r service; do
        [[ "$service" == "argo" ]] && has_argo=1
    done < <("${COMPOSE[@]}" config --services)
    if [[ "$has_argo" == "1" ]]; then
        "${COMPOSE[@]}" up -d argo
    fi

    local version_output line_count=0
    version_output="$("${COMPOSE[@]}" exec -T "$DEPLOY_SERVICE" archivebox version </dev/null)"
    while IFS= read -r line && [[ "$line_count" -lt 40 ]]; do
        printf '%s\n' "$line"
        line_count=$((line_count + 1))
    done <<<"$version_output"
    "${COMPOSE[@]}" exec -T "$DEPLOY_SERVICE" /opt/archivebox/lib/env/bin/curl -fsS --max-time 10 --connect-timeout 2 -H 'Host: admin.archivebox.io' http://127.0.0.1:8000/health/ </dev/null
    printf '%s\n' "$digest" > "$STATE_FILE"
}

mkdir -p "$(dirname "$STATE_FILE")"
touch "$STATE_FILE"

while :; do
    digest="$(remote_digest || true)"
    last_digest=""
    IFS= read -r last_digest < "$STATE_FILE" || true

    if [[ -z "$digest" ]]; then
        echo "[!] Could not resolve ${DEPLOY_IMAGE}; retrying in ${DEPLOY_INTERVAL}s" >&2
    elif [[ "$digest" != "$last_digest" ]]; then
        deploy_digest "$digest"
    else
        echo "[=] ${DEPLOY_IMAGE} already deployed at ${digest}"
    fi

    if [[ "${WATCH_ONCE:-0}" == "1" ]]; then
        break
    fi
    read -r -t "$DEPLOY_INTERVAL" _ </dev/null || true
done
