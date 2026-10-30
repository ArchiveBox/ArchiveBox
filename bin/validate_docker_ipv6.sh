#!/usr/bin/env bash
# Verify the packaged entrypoint, bind configuration, real IPv6 HTTP, and healthcheck.
set -Eeuo pipefail

IMAGE="${IMAGE:-archivebox/archivebox:dev}"
DOCKER_BINARY="${DOCKER_BINARY:-docker}"
CURL_BINARY="${CURL_BINARY:-curl}"
name="archivebox-ipv6-check-$$"
network="$name-network"
cleanup() {
    status=$?
    if [[ "$status" != 0 ]]; then "$DOCKER_BINARY" logs "$name" || true; fi
    "$DOCKER_BINARY" rm -fv "$name" >/dev/null 2>&1 || true
    "$DOCKER_BINARY" network rm "$network" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
"$DOCKER_BINARY" network create --ipv6 "$network" >/dev/null
if startup_health=$("$DOCKER_BINARY" run --rm --entrypoint uv "$IMAGE" run --no-project python /app/bin/docker_healthcheck.py 2>&1); then
    echo "FAIL: healthcheck succeeded before any server started" >&2
    exit 1
else
    [[ "$?" == 1 ]]
    [[ "$startup_health" == 'No healthy ArchiveBox HTTP listener for this collection' ]]
fi
echo "PASS: healthcheck fails before any server starts"

modes=("$@")
if [[ ${#modes[@]} == 0 ]]; then modes=(default wildcard loopback override debug debug-wildcard link-local link-local-debug link-local-reload); fi
for mode in "${modes[@]}"; do
    command=()
    environment=()
    published_ports=()
    family=--ipv6
    target='[::1]'
    headers=()
    case "$mode" in
        default) port=5797; family=--ipv4; target=127.0.0.1 ;;
        wildcard) port=5799; environment=(-e "BIND_ADDR=[::]:$port") ;;
        loopback) port=5800; environment=(-e "BIND_ADDR=[::1]:$port" -e PUID=1101 -e PGID=1102) ;;
        override) port=5801; environment=(-e BIND_ADDR=127.0.0.1:5797); command=(server --init "[::1]:$port") ;;
        debug) port=5802; environment=(-e "BIND_ADDR=[::1]:$port"); command=(server --init --debug) ;;
        debug-wildcard) port=5803; environment=(-e "BIND_ADDR=[::]:$port"); command=(server --init --debug) ;;
        link-local|link-local-debug|link-local-reload)
            port=5804
            flags=()
            if [[ "$mode" == link-local-debug ]]; then flags=(--debug); fi
            if [[ "$mode" == link-local-reload ]]; then flags=(--reload); fi
            # Docker assigns the actual link-local address. Wait for the
            # kernel's duplicate-address detection before asking ArchiveBox to bind.
            startup=$(cat <<'PY'
import ipaddress
import os
from pathlib import Path
import sys
import time

deadline = time.monotonic() + 10
while True:
    for line in Path('/proc/net/if_inet6').read_text().splitlines():
        raw, _, _, _, flags, interface = line.split()
        address = ipaddress.IPv6Address(int(raw, 16))
        if not address.is_link_local:
            continue
        assert not (int(flags, 16) & 0x08), 'IPv6 duplicate-address detection failed'
        if not (int(flags, 16) & 0x40):
            os.environ['BIND_ADDR'] = f'[{address}%{interface}]:{sys.argv[1]}'
            os.execvp('archivebox', ['archivebox', 'server', '--init', *sys.argv[2:]])
    assert time.monotonic() < deadline, 'No ready link-local address on the Docker IPv6 network'
    time.sleep(0.05)
PY
)
            command=(/usr/bin/env uv run --no-project python -c "$startup" "$port" "${flags[@]}")
            headers=(-H 'Host: localhost')
            ;;
        *) echo "Unknown IPv6 validation mode: $mode" >&2; exit 1 ;;
    esac
    if [[ "$mode" == *wildcard ]]; then published_ports=(-p "127.0.0.1::$port" -p "[::1]::$port"); fi
    "$DOCKER_BINARY" run -d --name "$name" --network "$network" --health-interval=1s --health-timeout=10s \
        -e PLUGINS=hashes -e SEARCH_BACKEND_ENGINE=sqlite -e SEARCH_BACKEND_SONIC_ENABLED=False \
        -e USE_COLOR=False -e SHOW_PROGRESS=False \
        "${published_ports[@]}" "${environment[@]}" "$IMAGE" "${command[@]}" >/dev/null
    if [[ "$mode" == link-local* ]]; then
        scoped_host=$("$DOCKER_BINARY" exec "$name" uv run --no-project python -c \
            'import ipaddress,psutil,socket; print(next(a.address for addresses in psutil.net_if_addrs().values() for a in addresses if a.family == socket.AF_INET6 and ipaddress.ip_address(a.address.split("%")[0]).is_link_local))')
        target="[${scoped_host/\%/%25}]"
    fi
    ready=0
    for ((attempt=0; attempt<60; attempt++)); do
        if "$DOCKER_BINARY" exec "$name" curl --noproxy '*' "$family" -fsS --max-time 2 \
            "${headers[@]}" "http://$target:$port/health/" >/dev/null 2>&1; then ready=1; break; fi
        [[ $("$DOCKER_BINARY" inspect -f '{{.State.Running}}' "$name") == true ]]
        sleep 1
    done
    [[ "$ready" == 1 ]]
    response=$("$DOCKER_BINARY" exec "$name" curl --noproxy '*' "$family" -fsS -i --max-time 5 "${headers[@]}" "http://$target:$port/health/")
    [[ $(printf '%s' "$response" | tr '[:upper:]' '[:lower:]') == *"x-archivebox-health: ok"* ]]
    [[ "$response" == *OK ]]
    "$DOCKER_BINARY" exec "$name" uv run --no-project python /app/bin/docker_healthcheck.py
    healthy=0
    for ((attempt=0; attempt<15; attempt++)); do
        if [[ $("$DOCKER_BINARY" inspect -f '{{.State.Health.Status}}' "$name") == healthy ]]; then healthy=1; break; fi
        sleep 1
    done
    [[ "$healthy" == 1 ]]
    echo "PASS: $mode serves HTTP over $family on $target:$port and Docker reports healthy"

    if [[ "$mode" == *wildcard ]]; then
        address=$("$DOCKER_BINARY" inspect -f '{{range .NetworkSettings.Networks}}{{.GlobalIPv6Address}}{{end}}' "$name")
        [[ "$address" == *:* ]]
        peer_response=$("$DOCKER_BINARY" run --rm --network "$network" --entrypoint curl "$IMAGE" \
            --noproxy '*' --ipv6 -fsS --max-time 5 "http://[$address]:$port/health/")
        [[ "$peer_response" == OK ]]
        echo "PASS: a separate container reaches the wildcard listener over IPv6"
        ipv4_response=$("$DOCKER_BINARY" exec "$name" curl --noproxy '*' --ipv4 -fsS --max-time 5 "http://127.0.0.1:$port/health/")
        [[ "$ipv4_response" == OK ]]
        published_addresses=$("$DOCKER_BINARY" port "$name" "$port/tcp")
        [[ "$published_addresses" == *'127.0.0.1:'* && "$published_addresses" == *'[::1]:'* ]]
        while read -r published; do
            published_family=--ipv4
            if [[ "$published" == '[::1]:'* ]]; then published_family=--ipv6; fi
            published_response=$("$CURL_BINARY" --noproxy '*' "$published_family" -fsS --max-time 5 "http://$published/health/")
            [[ "$published_response" == OK ]]
        done <<< "$published_addresses"
        echo "PASS: $mode serves IPv4 directly and through Docker's IPv4 and IPv6 published ports"
    fi

    if [[ "$mode" == loopback ]]; then
        if "$DOCKER_BINARY" exec "$name" curl --noproxy '*' --ipv4 -fsS --max-time 2 "http://127.0.0.1:$port/health/" >/dev/null 2>&1; then
            echo "FAIL: IPv6 loopback binding unexpectedly accepts IPv4" >&2
            exit 1
        else
            [[ "$?" == 7 ]]
        fi
        "$DOCKER_BINARY" exec "$name" supervisorctl -s unix:///tmp/archivebox/supervisord.sock stop worker_uvicorn
        if stopped_health=$("$DOCKER_BINARY" exec "$name" uv run --no-project python /app/bin/docker_healthcheck.py 2>&1); then
            echo "FAIL: stopped HTTP worker remains healthy" >&2
            exit 1
        else
            [[ "$?" == 1 ]]
            [[ "$stopped_health" == 'No healthy ArchiveBox HTTP listener for this collection' ]]
        fi
        echo "PASS: stopped HTTP worker fails healthcheck"
    fi
    "$DOCKER_BINARY" rm -fv "$name" >/dev/null
done
