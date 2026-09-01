#!/usr/bin/env bash

set -Eeuo pipefail

IMAGE="${IMAGE:-archivebox/archivebox:dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENTRYPOINT_PATH="${ENTRYPOINT_PATH:-$REPO_DIR/bin/docker_entrypoint.sh}"
COMPOSE_PATH="${COMPOSE_PATH:-$REPO_DIR/docker-compose.yml}"
RUN_ID="${RUN_ID:-${EPOCHSECONDS:-0}-$$}"
VALIDATION_ROOT="${VALIDATION_ROOT:-$REPO_DIR/tmp/docker-uid-gid-validation/$RUN_ID}"
KEEP_VALIDATION_ROOT="${KEEP_VALIDATION_ROOT:-0}"

REMOTE_HOST=""
LOCAL_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            REMOTE_HOST="$2"
            shift 2
            ;;
        --local-only)
            LOCAL_ONLY=1
            shift
            ;;
        --entrypoint)
            ENTRYPOINT_PATH="$2"
            shift 2
            ;;
        --workdir)
            VALIDATION_ROOT="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--remote HOST] [--local-only] [--entrypoint PATH] [--workdir PATH]" >&2
            exit 2
            ;;
    esac
done

ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${LIB_DIR:-$HOME/.config/archivebox/lib}}"
ABXPKG_SPEC="$(UV_LOCK_PATH="$REPO_DIR/uv.lock" uv run --no-cache --no-project python -c 'import os, tomllib; package = next(item for item in tomllib.load(open(os.environ["UV_LOCK_PATH"], "rb"))["package"] if item["name"] == "abxpkg"); wheel = package["wheels"][0]; print("abxpkg @ {}#{}".format(wheel["url"], wheel["hash"].replace(":", "=")))')"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"
uv run --no-cache --no-project --with "$ABXPKG_SPEC" abxpkg env \
    --install \
    --lib="$ABXPKG_LIB_DIR" \
    --deps-from="$REPO_DIR/.github/configs/ci-tooling.json:docker_validation_binaries" \
    >/dev/null
export PATH="$ABXPKG_LIB_DIR/env/bin:$PATH"
DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/docker"
SUDO_BINARY="$ABXPKG_LIB_DIR/env/bin/sudo"
SSH_BINARY="$ABXPKG_LIB_DIR/env/bin/ssh"
UNAME_BINARY="$ABXPKG_LIB_DIR/env/bin/uname"
test -x "$DOCKER_BINARY"
test -x "$SUDO_BINARY"
test -x "$SSH_BINARY"
test -x "$UNAME_BINARY"

if [[ -n "$REMOTE_HOST" && "$LOCAL_ONLY" != "1" ]]; then
    remote_dir="/tmp/archivebox-uid-gid-validation-$RUN_ID"
    entrypoint_name="${ENTRYPOINT_PATH##*/}"
    script_name="${0##*/}"
    "$SSH_BINARY" "$REMOTE_HOST" "mkdir -p '$remote_dir'"
    "$SSH_BINARY" "$REMOTE_HOST" "cat > '$remote_dir/$script_name'" < "$0"
    "$SSH_BINARY" "$REMOTE_HOST" "cat > '$remote_dir/$entrypoint_name'" < "$ENTRYPOINT_PATH"
    "$SSH_BINARY" "$REMOTE_HOST" "cat > '$remote_dir/docker-compose.yml'" < "$COMPOSE_PATH"
    "$SSH_BINARY" "$REMOTE_HOST" "cd '$remote_dir' && IMAGE='$IMAGE' ENTRYPOINT_PATH='$remote_dir/$entrypoint_name' COMPOSE_PATH='$remote_dir/docker-compose.yml' bash './$script_name' --local-only --entrypoint '$remote_dir/$entrypoint_name' --workdir '$remote_dir/work'"
    exit $?
fi

DOCKER_PLATFORM="${DOCKER_PLATFORM:-}"
if [[ -z "$DOCKER_PLATFORM" ]]; then
    case "$("$UNAME_BINARY" -m)" in
        arm64|aarch64) DOCKER_PLATFORM="linux/amd64" ;;
    esac
fi

docker_base=("$DOCKER_BINARY" run --rm)
if [[ -n "$DOCKER_PLATFORM" ]]; then
    docker_base+=(--platform "$DOCKER_PLATFORM")
fi

mkdir -p "$VALIDATION_ROOT"

total=0
passed=0
failed=0

log() {
    printf '%s\n' "$*"
}

safe_name() {
    printf '%s' "$1" | tr -cs 'A-Za-z0-9_.-' '-'
}

docker_setup() {
    local case_dir="$1"
    local setup_script="$2"
    mkdir -p "$case_dir"
    "${docker_base[@]}" \
        -v "$case_dir:/case" \
        --entrypoint /bin/bash \
        "$IMAGE" \
        -lc "set -Eeuo pipefail
            rm -rf /case/data /case/lib /case/browsers
            mkdir -p /case/data /case/lib /case/browsers
            chown 0:0 /case/data /case/lib /case/browsers
            chmod 755 /case/data /case/lib /case/browsers
            $setup_script"
}

# These command strings intentionally expand only inside the validation container.
# shellcheck disable=SC2016
default_cmd='printf "ABX_UID=%s\nABX_GID=%s\nABX_USER=%s\nABX_GROUPS=%s\n" "$(id -u)" "$(id -g)" "$(whoami 2>/dev/null || true)" "$(id -Gn)"; touch /data/logs/probe /data/archive/probe "$ABXPKG_LIB_DIR/probe" "$PERSONAS_DIR/Default/chrome_profile/probe"; stat -c "ABX_STAT %u:%g:%a %n" /data /data/logs /data/archive "$ABXPKG_LIB_DIR" "$PERSONAS_DIR" "$PERSONAS_DIR/Default" "$PERSONAS_DIR/Default/chrome_profile"; echo ABX_PERSONA_PROFILE_OK; echo ABX_OK'
# shellcheck disable=SC2016
runtime_dependency_cmd="$default_cmd"'; mkdir -p "$ABXPKG_LIB_DIR/chromewebstore/extensions/cookie/_metadata"; touch "$ABXPKG_LIB_DIR/chromewebstore/extensions/cookie/_metadata/rules.fbs"; echo ABX_CHROME_EXTENSION_CACHE_OK'
# shellcheck disable=SC2016
full_flow_cmd='set -Eeuo pipefail
printf "ABX_UID=%s\nABX_GID=%s\nABX_USER=%s\nABX_GROUPS=%s\n" "$(id -u)" "$(id -g)" "$(whoami 2>/dev/null || true)" "$(id -Gn)"
id -Gn | grep -qw audio
id -Gn | grep -qw video
mkdir -p "$PERSONAS_DIR/Default/chrome_profile"
touch "$PERSONAS_DIR/Default/chrome_profile/probe"
rm -f "$PERSONAS_DIR/Default/chrome_profile/probe"
archivebox init
archivebox install 2>&1 | tee /tmp/archivebox-install.log
if grep -E "(/[[:alnum:]_.-]+/)?pip install|npm install|uv pip install" /tmp/archivebox-install.log; then
    echo "ABX_UNEXPECTED_RUNTIME_INSTALL"
    exit 1
fi
archivebox version 2>&1 | tee /tmp/archivebox-version.log
grep -Eq "/opt/archivebox/lib/(uv/venv/bin|env/bin)/trafilatura" /tmp/archivebox-version.log
grep -Eq "/opt/archivebox/lib/(pnpm/packages/defuddle/node_modules/.bin|env/bin)/defuddle" /tmp/archivebox-version.log
grep -Eq "/opt/archivebox/lib/env/bin/sonic" /tmp/archivebox-version.log
archivebox add --depth=0 https://example.com/ 2>&1 | tee /tmp/archivebox-add.log
archivebox update --index-only 2>&1 | tee /tmp/archivebox-update.log
snapshot_dir="$(find /data/archive/users/system/snapshots -mindepth 3 -maxdepth 3 -type d | head -n 1)"
test -n "$snapshot_dir"
test -s "$snapshot_dir/index.html"
test -s "$snapshot_dir/wget/example.com/index.html"
test -s "$snapshot_dir/dom/output.html"
test -s "$snapshot_dir/screenshot/screenshot.png"
test -s "$snapshot_dir/pdf/output.pdf"
test -s "$snapshot_dir/singlefile/singlefile.html"
test -s "$snapshot_dir/headers/headers.json"
test -s "$snapshot_dir/readability/content.txt"
test -s "$snapshot_dir/trafilatura/content.txt"
test -s "$snapshot_dir/defuddle/content.txt"
test -s "$snapshot_dir/liteparse/content.txt"
test -s "$snapshot_dir/responses/index.jsonl"
test -s "$snapshot_dir/search_backend_sonic/on_Snapshot__91_index_sonic."*.sh
test -s "$snapshot_dir/search_backend_sqlite/on_Snapshot__90_index_sqlite."*.sh
grep -R "Example Domain" \
    "$snapshot_dir/wget/example.com/index.html" \
    "$snapshot_dir/dom/output.html" \
    "$snapshot_dir/readability/content.txt" \
    "$snapshot_dir/trafilatura/content.txt" \
    "$snapshot_dir/defuddle/content.txt" \
    "$snapshot_dir/liteparse/content.txt"
if grep -R "Permission denied\\|Operation not permitted" /tmp/archivebox-add.log /tmp/archivebox-update.log /data/logs 2>/dev/null; then
    echo "ABX_PERMISSION_ERROR_IN_FULL_FLOW"
    exit 1
fi
find "$snapshot_dir" -maxdepth 2 -type f | sort | sed "s#^#ABX_OUTPUT #"
echo ABX_OK'

run_case() {
    local name="$1"
    local setup_script="$2"
    local env_string="$3"
    local user_spec="$4"
    local expected_status="$5"
    local expected_uid="$6"
    local expected_gid="$7"
    local command="${8:-$default_cmd}"
    local post_assert="${9:-}"

    total=$((total + 1))
    local slug case_dir log_file status
    slug="$(safe_name "$name")"
    case_dir="$VALIDATION_ROOT/$slug"
    log_file="$case_dir/output.log"

    docker_setup "$case_dir" "$setup_script"

    local run_args=("${docker_base[@]}")
    if [[ "$user_spec" != "-" ]]; then
        run_args+=(--user "$user_spec")
    fi
    run_args+=(
        -e DATA_DIR=/data
        -e ABXPKG_LIB_DIR=/libdir
        -e PLAYWRIGHT_BROWSERS_PATH=/browsers
    )

    if [[ -n "$env_string" && "$env_string" != "-" ]]; then
        local env_parts=()
        read -r -a env_parts <<< "$env_string"
        local env_pair
        for env_pair in "${env_parts[@]}"; do
            run_args+=(-e "$env_pair")
        done
    fi

    run_args+=(
        -v "$ENTRYPOINT_PATH:/app/bin/docker_entrypoint.sh:ro"
        -v "$case_dir/data:/data"
        -v "$case_dir/lib:/libdir"
        -v "$case_dir/browsers:/browsers"
        --entrypoint /app/bin/docker_entrypoint.sh
        "$IMAGE"
        sh -c "$command"
    )

    set +e
    "${run_args[@]}" >"$log_file" 2>&1
    status=$?
    set -e

    local ok=1
    if [[ "$expected_status" == "pass" && "$status" != "0" ]]; then
        ok=0
    elif [[ "$expected_status" == "fail" && "$status" == "0" ]]; then
        ok=0
    fi

    if [[ "$expected_status" == "pass" ]]; then
        if [[ -n "$expected_uid" ]] && ! grep -q "^ABX_UID=$expected_uid$" "$log_file"; then
            ok=0
        fi
        if [[ -n "$expected_gid" ]] && ! grep -q "^ABX_GID=$expected_gid$" "$log_file"; then
            ok=0
        fi
        if ! grep -q '^ABX_OK$' "$log_file"; then
            ok=0
        fi
        if [[ "$user_spec" == "-" ]]; then
            grep '^ABX_GROUPS=' "$log_file" | grep -qw audio || ok=0
            grep '^ABX_GROUPS=' "$log_file" | grep -qw video || ok=0
            grep -q '^ABX_PERSONA_PROFILE_OK$' "$log_file" || ok=0
        fi
    fi

    if [[ "$post_assert" == "nested-root-stays" ]]; then
        local nested_stat
        nested_stat="$("${docker_base[@]}" -v "$case_dir/data:/data" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /data/archive/existing/file" 2>/dev/null || true)"
        [[ "$nested_stat" == "0:0" ]] || ok=0
    elif [[ "$post_assert" == runtime-nested-root-stays ]]; then
        local lib_stat browsers_stat chrome_rules_stat chrome_metadata_stat
        lib_stat="$("${docker_base[@]}" -v "$case_dir/lib:/libdir" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /libdir/existing/file" 2>/dev/null || true)"
        browsers_stat="$("${docker_base[@]}" -v "$case_dir/browsers:/browsers" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /browsers/existing/file" 2>/dev/null || true)"
        chrome_rules_stat="$("${docker_base[@]}" -v "$case_dir/lib:/libdir" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /libdir/chromewebstore/extensions/cookie/rules.json" 2>/dev/null || true)"
        chrome_metadata_stat="$("${docker_base[@]}" -v "$case_dir/lib:/libdir" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /libdir/chromewebstore/extensions/cookie/_metadata/rules.fbs" 2>/dev/null || true)"
        [[ "$lib_stat" == "0:0" \
            && "$browsers_stat" == "0:0" \
            && "$chrome_rules_stat" == "$expected_uid:$expected_gid" \
            && "$chrome_metadata_stat" == "$expected_uid:$expected_gid" ]] || ok=0
    elif [[ "$post_assert" == users-dir-repaired ]]; then
        local users_stat
        users_stat="$("${docker_base[@]}" -v "$case_dir/data:/data" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /data/users" 2>/dev/null || true)"
        [[ "$users_stat" == "$expected_uid:$expected_gid" ]] || ok=0
    elif [[ "$post_assert" == config-files-repaired ]]; then
        local config_stat index_stat
        config_stat="$("${docker_base[@]}" -v "$case_dir/data:/data" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /data/ArchiveBox.conf" 2>/dev/null || true)"
        index_stat="$("${docker_base[@]}" -v "$case_dir/data:/data" --entrypoint /bin/bash "$IMAGE" -lc "stat -c '%u:%g' /data/index.sqlite3" 2>/dev/null || true)"
        [[ "$config_stat" == "$expected_uid:$expected_gid" && "$index_stat" == "$expected_uid:$expected_gid" ]] || ok=0
    fi

    if [[ "$ok" == "1" ]]; then
        passed=$((passed + 1))
        log "PASS $name"
    else
        failed=$((failed + 1))
        log "FAIL $name (status=$status expected=$expected_status log=$log_file)"
        sed -n '1,160p' "$log_file"
    fi
}

run_readonly_case() {
    local name="$1"
    local setup_script="$2"
    local env_string="$3"
    local user_spec="$4"

    total=$((total + 1))
    local slug case_dir log_file status ok
    slug="$(safe_name "$name")"
    case_dir="$VALIDATION_ROOT/$slug"
    log_file="$case_dir/output.log"
    docker_setup "$case_dir" "$setup_script"

    local run_args=("${docker_base[@]}")
    if [[ "$user_spec" != "-" ]]; then
        run_args+=(--user "$user_spec")
    fi
    run_args+=(
        -e DATA_DIR=/data
        -e ABXPKG_LIB_DIR=/libdir
        -e PLAYWRIGHT_BROWSERS_PATH=/browsers
    )
    if [[ -n "$env_string" && "$env_string" != "-" ]]; then
        local env_parts=()
        read -r -a env_parts <<< "$env_string"
        local env_pair
        for env_pair in "${env_parts[@]}"; do
            run_args+=(-e "$env_pair")
        done
    fi
    run_args+=(
        -v "$ENTRYPOINT_PATH:/app/bin/docker_entrypoint.sh:ro"
        -v "$case_dir/data:/data:ro"
        -v "$case_dir/lib:/libdir:ro"
        -v "$case_dir/browsers:/browsers:ro"
        --entrypoint /app/bin/docker_entrypoint.sh
        "$IMAGE"
        sh -c "$default_cmd"
    )

    set +e
    "${run_args[@]}" >"$log_file" 2>&1
    status=$?
    set -e

    ok=0
    if [[ "$status" != "0" ]] && grep -q "cannot write to /data" "$log_file"; then
        ok=1
    fi
    if [[ "$ok" == "1" ]]; then
        passed=$((passed + 1))
        log "PASS $name"
    else
        failed=$((failed + 1))
        log "FAIL $name (status=$status expected=readonly failure log=$log_file)"
        sed -n '1,160p' "$log_file"
    fi
}

run_full_flow_case() {
    local name="$1"
    local setup_script="$2"
    local env_string="$3"
    local user_spec="$4"
    local expected_uid="$5"
    local expected_gid="$6"

    total=$((total + 1))
    local slug case_dir log_file status ok
    slug="$(safe_name "$name")"
    case_dir="$VALIDATION_ROOT/$slug"
    log_file="$case_dir/output.log"
    docker_setup "$case_dir" "$setup_script"

    local run_args=("${docker_base[@]}")
    if [[ "$user_spec" != "-" ]]; then
        run_args+=(--user "$user_spec")
    fi
    run_args+=(
        -e DATA_DIR=/data
    )
    if [[ -n "$env_string" && "$env_string" != "-" ]]; then
        local env_parts=()
        read -r -a env_parts <<< "$env_string"
        local env_pair
        for env_pair in "${env_parts[@]}"; do
            run_args+=(-e "$env_pair")
        done
    fi
    run_args+=(
        -v "$ENTRYPOINT_PATH:/app/bin/docker_entrypoint.sh:ro"
        -v "$case_dir/data:/data"
        --entrypoint /app/bin/docker_entrypoint.sh
        "$IMAGE"
        bash -lc "$full_flow_cmd"
    )

    set +e
    "${run_args[@]}" >"$log_file" 2>&1
    status=$?
    set -e

    ok=1
    [[ "$status" == "0" ]] || ok=0
    grep -q "^ABX_UID=$expected_uid$" "$log_file" || ok=0
    grep -q "^ABX_GID=$expected_gid$" "$log_file" || ok=0
    grep '^ABX_GROUPS=' "$log_file" | grep -qw audio || ok=0
    grep '^ABX_GROUPS=' "$log_file" | grep -qw video || ok=0
    grep -q '^ABX_OK$' "$log_file" || ok=0
    grep -q 'total urls snapshotted: 1' "$log_file" || ok=0
    grep -q 'Search Reindex Complete' "$log_file" || ok=0
    grep -q 'ABX_OUTPUT .*/wget/example.com/index.html' "$log_file" || ok=0
    grep -q 'ABX_OUTPUT .*/screenshot/screenshot.png' "$log_file" || ok=0
    grep -q 'ABX_OUTPUT .*/trafilatura/content.txt' "$log_file" || ok=0

    if [[ "$ok" == "1" ]]; then
        passed=$((passed + 1))
        log "PASS $name"
    else
        failed=$((failed + 1))
        log "FAIL $name (status=$status expected=full-flow success log=$log_file)"
        sed -n '1,220p' "$log_file"
    fi
}

run_mount_case() {
    local fs_name="$1"
    local mount_dir="$2"

    [[ -n "$mount_dir" ]] || { log "FAIL $fs_name mount case: mount dir not provided"; exit 1; }
    [[ -d "$mount_dir" ]] || { log "FAIL $fs_name mount case: $mount_dir does not exist"; exit 1; }
    [[ -w "$mount_dir" ]] || { log "FAIL $fs_name mount case: $mount_dir is not writable by host user"; exit 1; }

    local previous_root case_root
    previous_root="$VALIDATION_ROOT"
    case_root="$mount_dir/archivebox-uidgid-validation-$RUN_ID"
    mkdir -p "$case_root"
    VALIDATION_ROOT="$case_root"
    run_case "$fs_name writable forced-owner style mount" ":" "-" "-" pass 911 911 "$default_cmd" ""
    VALIDATION_ROOT="$previous_root"
}

run_compose_personas_case() {
    total=$((total + 1))
    local case_dir="$VALIDATION_ROOT/compose-personas-persist"
    local log_file="$case_dir/output.log"
    local status
    mkdir -p "$case_dir/data"

    set +e
    # shellcheck disable=SC2016
    ARCHIVEBOX_IMAGE="$IMAGE" "$DOCKER_BINARY" compose \
        --project-directory "$case_dir" \
        -f "$COMPOSE_PATH" \
        run --rm -T archivebox sh -c \
        'printf "ABX_UID=%s\nABX_GID=%s\n" "$(id -u)" "$(id -g)"; archivebox init; printf persisted > "$PERSONAS_DIR/Default/chrome_profile/persisted"; echo ABX_OK' \
        >"$log_file" 2>&1
    status=$?
    "$DOCKER_BINARY" compose --project-directory "$case_dir" -f "$COMPOSE_PATH" down --volumes --remove-orphans >/dev/null 2>&1
    set -e

    if [[ "$status" == "0" ]] \
        && grep -q '^ABX_OK$' "$log_file" \
        && [[ -f "$case_dir/data/personas/Default/chrome_profile/persisted" ]] \
        && [[ "$(< "$case_dir/data/personas/Default/chrome_profile/persisted")" == persisted ]]; then
        passed=$((passed + 1))
        log "PASS compose persists persona data outside the inherited anonymous volume"
    else
        failed=$((failed + 1))
        log "FAIL compose persists persona data outside the inherited anonymous volume (status=$status log=$log_file)"
        sed -n '1,160p' "$log_file"
    fi
}

log "Running UID/GID validation on ${HOSTNAME:-unknown-host} using image=$IMAGE entrypoint=$ENTRYPOINT_PATH root=$VALIDATION_ROOT platform=${DOCKER_PLATFORM:-native}"

run_case "root-owned empty data auto-detect default" \
    "chown 0:0 /case/data && chmod 755 /case/data" \
    "-" "-" pass 911 911

run_case "501-owned data auto-detected" \
    "chown 501:20 /case/data && chmod 755 /case/data" \
    "-" "-" pass 501 20

run_case "non-root data with root-owned config files repaired" \
    "chown 501:20 /case/data && chmod 755 /case/data && touch /case/data/index.sqlite3 /case/data/ArchiveBox.conf && mkdir -p /case/data/archive/users && chown 0:0 /case/data/index.sqlite3 /case/data/ArchiveBox.conf /case/data/archive/users" \
    "-" "-" pass 501 20 "$default_cmd" config-files-repaired

run_case "911-owned data auto-detected" \
    "chown 911:911 /case/data && chmod 755 /case/data" \
    "-" "-" pass 911 911

run_case "root-owned data falls back to default archivebox user" \
    "chown 0:0 /case/data && chmod 755 /case/data" \
    "-" "-" pass 911 911

run_case "nested root-owned archive content is not recursively chowned" \
    "chown 0:0 /case/data && chmod 755 /case/data && mkdir -p /case/data/archive/existing && touch /case/data/archive/existing/file && chown -R 0:0 /case/data/archive/existing" \
    "-" "-" pass 911 911 "$default_cmd" nested-root-stays

run_case "only the writable Chrome extension cache is recursively repaired" \
    "chown 501:20 /case/data && mkdir -p /case/lib/existing /case/lib/chromewebstore/extensions/cookie /case/browsers/existing && touch /case/lib/existing/file /case/lib/chromewebstore/extensions/cookie/rules.json /case/browsers/existing/file && chown -R 0:0 /case/lib/existing /case/lib/chromewebstore /case/browsers/existing" \
    "-" "-" pass 501 20 "$runtime_dependency_cmd" runtime-nested-root-stays

run_case "root start fixes read-only top-level data when chmod works" \
    "chown 0:0 /case/data && chmod 555 /case/data" \
    "-" "-" pass 911 911

run_case "legacy data users dir repaired when present" \
    "chown 911:911 /case/data && chmod 755 /case/data && mkdir -p /case/data/users && chown 0:0 /case/data/users" \
    "-" "-" pass 911 911 "$default_cmd" users-dir-repaired

run_case "archive dir root-owned inside 911 data repaired shallowly" \
    "chown 911:911 /case/data && chmod 755 /case/data && mkdir -p /case/data/archive && chown 0:0 /case/data/archive" \
    "-" "-" pass 911 911

run_case "logs dir root-owned mode 000 repaired shallowly" \
    "chown 911:911 /case/data && chmod 755 /case/data && mkdir -p /case/data/logs && chown 0:0 /case/data/logs && chmod 000 /case/data/logs" \
    "-" "-" pass 911 911

run_case "1001-owned data auto-detected" \
    "chown 1001:1001 /case/data && chmod 755 /case/data" \
    "-" "-" pass 1001 1001

run_case "root-owned ArchiveBox.conf only is repaired" \
    "chown 911:911 /case/data && chmod 755 /case/data && touch /case/data/ArchiveBox.conf /case/data/index.sqlite3 && chown 0:0 /case/data/ArchiveBox.conf /case/data/index.sqlite3" \
    "-" "-" pass 911 911 "$default_cmd" config-files-repaired

run_compose_personas_case

run_mount_case "NFS" "${NFS_TEST_DIR:-}"
run_mount_case "SMB" "${SMB_TEST_DIR:-}"

log "SUMMARY passed=$passed failed=$failed total=$total"

if [[ "$KEEP_VALIDATION_ROOT" != "1" ]]; then
    "$SUDO_BINARY" rm -rf "$VALIDATION_ROOT"
fi

[[ "$failed" == "0" ]]
