#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${IMAGE:-archivebox/archivebox:dev}"
DOCKER_BINARY="${DOCKER_BINARY:-docker}"
CURL_BINARY="${CURL_BINARY:-curl}"
name="archivebox-port-check-$$"
volume="$name-data"
cookies=$(mktemp)
cleanup() {
    status=$?
    if [[ "$status" != 0 ]]; then "$DOCKER_BINARY" logs "$name" || true; fi
    "$DOCKER_BINARY" rm -fv "$name" >/dev/null 2>&1 || true
    "$DOCKER_BINARY" volume rm "$volume" >/dev/null
    rm -f "$cookies"
    exit "$status"
}
"$DOCKER_BINARY" volume create "$volume" >/dev/null
trap cleanup EXIT

"$DOCKER_BINARY" run --rm -v "$volume:/data" "$IMAGE" init
"$DOCKER_BINARY" run --rm -v "$volume:/data" \
    -e DJANGO_SUPERUSER_USERNAME=portcheck -e DJANGO_SUPERUSER_EMAIL=portcheck@example.com \
    -e DJANGO_SUPERUSER_PASSWORD="$name-password" "$IMAGE" manage createsuperuser --noinput

for mode in default debug; do
    command=()
    if [[ "$mode" == debug ]]; then command=(server --debug 0.0.0.0:5797); fi
    "$DOCKER_BINARY" run -d --name "$name" -v "$volume:/data" \
        -p 127.0.0.1::5797 "$IMAGE" "${command[@]}" >/dev/null
    address=$("$DOCKER_BINARY" port "$name" 5797/tcp)
    ready=0
    for ((attempt=0; attempt<60; attempt++)); do
        if "$CURL_BINARY" -fsS --max-time 2 "http://$address/health/" >/dev/null 2>&1; then ready=1; break; fi
        [[ $("$DOCKER_BINARY" inspect -f '{{.State.Running}}' "$name") == true ]]
        sleep 1
    done
    [[ "$ready" == 1 ]]
    body=$("$CURL_BINARY" -fsS --max-time 10 "http://$address/health/")
    [[ "$body" == *OK* ]]
    echo "PASS: $mode server responds through Docker mapping $address -> 5797"
    origin="http://admin.archivebox.localhost:${address##*:}"
    login=$("$CURL_BINARY" -fsS --max-time 10 -c "$cookies" "$origin/admin/login/?next=/admin/")
    csrf=$(printf '%s' "$login" | sed -n 's/.*name="csrfmiddlewaretoken" value="\([^"]*\)".*/\1/p')
    [[ -n "$csrf" ]]
    "$CURL_BINARY" -fsS --max-time 10 -b "$cookies" -c "$cookies" -e "$origin/admin/login/" \
        --data-urlencode username=portcheck --data-urlencode "password=$name-password" \
        --data-urlencode "csrfmiddlewaretoken=$csrf" --data-urlencode next=/admin/ \
        "$origin/admin/login/" >/dev/null
    page=$("$CURL_BINARY" -fsS --max-time 10 -b "$cookies" "$origin/admin/crawls/crawl/")
    [[ "$page" == *model-crawl* ]]
    [[ "$page" != *'name="password"'* ]]
    echo "PASS: $mode authenticated Crawls works on 5797 with the same browser session"
    "$DOCKER_BINARY" rm -fv "$name" >/dev/null
done
