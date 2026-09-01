#!/usr/bin/env bash
# ArchiveBox Setup Script (Ubuntu/Debian/FreeBSD/macOS)
#   - Project Homepage: https://github.com/ArchiveBox/ArchiveBox
#   - Install Documentation: https://github.com/ArchiveBox/ArchiveBox/wiki/Install
# Script Usage:
#    curl -fsSL 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh' | bash
#           (aka https://get.archivebox.io)

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
set -e
set -u
if (set -o pipefail) 2>/dev/null; then
    set -o pipefail
fi
if (set -o errtrace) 2>/dev/null; then
    set -o errtrace
fi
if [ -t 1 ]; then
    clear || true
fi

RUNNING_AS_ROOT="false"
ARCHIVEBOX_SYSTEM_USER="archivebox"
ARCHIVEBOX_SYSTEM_UID=""
ARCHIVEBOX_SYSTEM_GID=""
FOLLOWUP_SUDO=""

if [ "$(id -u)" -eq 0 ]; then
    RUNNING_AS_ROOT="true"
    if ! id "$ARCHIVEBOX_SYSTEM_USER" >/dev/null 2>&1; then
        echo "[+] Creating the archivebox system user..."
        case "$(uname -s)" in
            Linux)
                useradd --system --create-home --home-dir /var/lib/archivebox --shell /bin/bash "$ARCHIVEBOX_SYSTEM_USER"
                ;;
            FreeBSD)
                pw useradd "$ARCHIVEBOX_SYSTEM_USER" -m -d /var/db/archivebox -s /bin/sh
                ;;
            Darwin)
                archivebox_uid=499
                while dscl . -search /Users UniqueID "$archivebox_uid" 2>/dev/null | grep -q .; do
                    archivebox_uid=$((archivebox_uid - 1))
                done
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER"
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER" RealName ArchiveBox
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER" UserShell /bin/bash
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER" UniqueID "$archivebox_uid"
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER" PrimaryGroupID 20
                dscl . -create "/Users/$ARCHIVEBOX_SYSTEM_USER" NFSHomeDirectory "/Users/$ARCHIVEBOX_SYSTEM_USER"
                mkdir -p "/Users/$ARCHIVEBOX_SYSTEM_USER"
                chown "$archivebox_uid:20" "/Users/$ARCHIVEBOX_SYSTEM_USER"
                ;;
            *)
                echo "[X] Cannot create the archivebox system user on $(uname -s)."
                exit 2
                ;;
        esac
    fi

    ARCHIVEBOX_SYSTEM_UID="$(id -u "$ARCHIVEBOX_SYSTEM_USER")"
    ARCHIVEBOX_SYSTEM_GID="$(id -g "$ARCHIVEBOX_SYSTEM_USER")"
    if command -v getent >/dev/null 2>&1; then
        HOME="$(getent passwd "$ARCHIVEBOX_SYSTEM_USER" | cut -d: -f6)"
    elif [ "$(uname -s)" = "FreeBSD" ]; then
        HOME="$(pw usershow "$ARCHIVEBOX_SYSTEM_USER" | cut -d: -f9)"
    else
        HOME="$(dscl . -read "/Users/$ARCHIVEBOX_SYSTEM_USER" NFSHomeDirectory | awk '{print $2}')"
    fi
    export HOME
fi

if [ "$RUNNING_AS_ROOT" = "true" ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    FOLLOWUP_SUDO="sudo "
fi

ARCHIVEBOX_BRANCH="${ARCHIVEBOX_BRANCH:-dev}"
ARCHIVEBOX_IMAGE="${ARCHIVEBOX_IMAGE:-archivebox/archivebox:dev}"
ARCHIVEBOX_PYTHON="${ARCHIVEBOX_PYTHON:-3.13}"
ARCHIVEBOX_PACKAGE="${ARCHIVEBOX_PACKAGE:-archivebox>=0.9.0rc0,<0.10}"
ARCHIVEBOX_PLATFORM="${ARCHIVEBOX_PLATFORM:-}"
ARCHIVEBOX_COMPOSE_URL="${ARCHIVEBOX_COMPOSE_URL:-https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/${ARCHIVEBOX_BRANCH}/docker-compose.yml}"
ABXPKG_PACKAGE="${ABXPKG_PACKAGE:-abxpkg==1.12.109}"
ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-$HOME/.cache/archivebox/setup-abxpkg}"
ARCHIVEBOX_HOME_DIR="$HOME/archivebox"
ARCHIVEBOX_DATA_DIR="$ARCHIVEBOX_HOME_DIR/data"
BOOTSTRAP_UV_BINARY=""
UV_BINARY=""
DOCKER_BINARY=""
CONTAINER_ENGINE_NAME=""
CONTAINER_ENGINE_LABEL=""
CURL_BINARY=""
OPEN_BINARY=""
ARCHIVEBOX_BINARY=""
DOCKER_PLATFORM_ARGS=""
if [ -n "$ARCHIVEBOX_PLATFORM" ]; then
    DOCKER_PLATFORM_ARGS="--platform $ARCHIVEBOX_PLATFORM"
fi
DOCKER_RUN_TTY_ARG="-i"
DOCKER_COMPOSE_RUN_TTY_ARG="-T"
if [ -t 0 ]; then
    DOCKER_RUN_TTY_ARG="-it"
    DOCKER_COMPOSE_RUN_TTY_ARG=""
fi

fix_root_install_ownership() {
    if [ "$RUNNING_AS_ROOT" != "true" ]; then
        return 0
    fi

    # Keep shared runtime parents writable after ArchiveBox drops privileges.
    for path in "$HOME/.local" "$HOME/.local/share" "$HOME/.cache" "$HOME/.cache/archivebox" "$HOME/.config"; do
        if [ -e "$path" ]; then
            chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$path"
        fi
    done

    # Only hand off bounded runtime roots. Provider libraries can be very large,
    # and their existing contents only need to remain readable/executable.
    for path in "$HOME/.local/bin" "$HOME/.local/share/uv" "$HOME/.cache/uv" "$HOME/.config/uv" "$ABXPKG_LIB_DIR" "$ABXPKG_LIB_DIR/env" "$ABXPKG_LIB_DIR/env/bin"; do
        if [ -e "$path" ]; then
            chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$path"
        fi
    done
}

run_as_archivebox_user() {
    if [ "$RUNNING_AS_ROOT" != "true" ]; then
        "$@"
        return
    fi

    if command -v runuser >/dev/null 2>&1; then
        (cd "$HOME" && runuser -u "$ARCHIVEBOX_SYSTEM_USER" -- env HOME="$HOME" PATH="$PATH" ABXPKG_LIB_DIR="$ABXPKG_LIB_DIR" "$@")
    else
        (cd "$HOME" && sudo -u "$ARCHIVEBOX_SYSTEM_USER" env HOME="$HOME" PATH="$PATH" ABXPKG_LIB_DIR="$ABXPKG_LIB_DIR" "$@")
    fi
}

ensure_archivebox_data_dir() {
    mkdir -p "$ARCHIVEBOX_DATA_DIR"
    if [ "$RUNNING_AS_ROOT" = "true" ]; then
        chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$ARCHIVEBOX_HOME_DIR" "$ARCHIVEBOX_DATA_DIR"
    fi
}

migrate_legacy_collection_dir() {
    if [ ! -f "$ARCHIVEBOX_HOME_DIR/index.sqlite3" ]; then
        return 0
    fi

    for path in "$ARCHIVEBOX_HOME_DIR"/* "$ARCHIVEBOX_HOME_DIR"/.[!.]* "$ARCHIVEBOX_HOME_DIR"/..?*; do
        if [ ! -e "$path" ] && [ ! -L "$path" ]; then
            continue
        fi
        case "$(basename "$path")" in
            data|docker-compose.yml|compose.yml|compose.yaml|.env|Caddyfile)
                continue
                ;;
        esac
        mv -n "$path" "$ARCHIVEBOX_DATA_DIR/"
    done
}

docker_pull_archivebox() {
    if [ -n "$ARCHIVEBOX_PLATFORM" ]; then
        "$DOCKER_BINARY" pull --platform "$ARCHIVEBOX_PLATFORM" "$ARCHIVEBOX_IMAGE"
    else
        "$DOCKER_BINARY" pull "$ARCHIVEBOX_IMAGE"
    fi
}

docker_run_archivebox() {
    if [ -n "$ARCHIVEBOX_PLATFORM" ]; then
        "$DOCKER_BINARY" run --platform "$ARCHIVEBOX_PLATFORM" "$DOCKER_RUN_TTY_ARG" -v "$PWD":/data --rm "$ARCHIVEBOX_IMAGE" "$@"
    else
        "$DOCKER_BINARY" run "$DOCKER_RUN_TTY_ARG" -v "$PWD":/data --rm "$ARCHIVEBOX_IMAGE" "$@"
    fi
}

docker_run_archivebox_init() {
    docker_run_archivebox init
}

docker_run_archivebox_install() {
    docker_run_archivebox install
}

docker_run_archivebox_server() {
    if [ -n "$ARCHIVEBOX_PLATFORM" ]; then
        "$DOCKER_BINARY" run --platform "$ARCHIVEBOX_PLATFORM" -v "$PWD":/data -d -p 8000:8000 --name=archivebox "$ARCHIVEBOX_IMAGE"
    else
        "$DOCKER_BINARY" run -v "$PWD":/data -d -p 8000:8000 --name=archivebox "$ARCHIVEBOX_IMAGE"
    fi
}

docker_compose_run_archivebox() {
    if [ -n "$DOCKER_COMPOSE_RUN_TTY_ARG" ]; then
        "$DOCKER_BINARY" compose run "$DOCKER_COMPOSE_RUN_TTY_ARG" --rm archivebox "$@"
    else
        "$DOCKER_BINARY" compose run --rm archivebox "$@"
    fi
}

wait_for_archivebox() {
    url="http://127.0.0.1:8000/health/"
    host_header="admin.archivebox.localhost:8000"
    attempts=60
    attempt=1

    while [ "$attempt" -le "$attempts" ]; do
        if "$CURL_BINARY" -fsS --connect-timeout 1 --max-time 2 -H "Host: ${host_header}" "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    echo "[!] Server process started, but health check did not become ready at $url after ${attempts}s."
    echo "    Inspect $ARCHIVEBOX_DATA_DIR/logs/ or run 'docker compose logs' to diagnose startup."
    return 1
}

open_archivebox() {
    if [ -n "$OPEN_BINARY" ] && [ -t 1 ]; then
        "$OPEN_BINARY" "http://admin.archivebox.localhost:8000/admin/" || true
    fi
}

ensure_uv() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v uv > /dev/null 2>&1; then
        BOOTSTRAP_UV_BINARY="$(command -v uv)"
        if [ "$RUNNING_AS_ROOT" = "true" ] && { [ "${BOOTSTRAP_UV_BINARY#/root/}" != "$BOOTSTRAP_UV_BINARY" ] || [ "${BOOTSTRAP_UV_BINARY#/var/root/}" != "$BOOTSTRAP_UV_BINARY" ]; }; then
            mkdir -p "$HOME/.local/bin"
            install -m 0755 "$BOOTSTRAP_UV_BINARY" "$HOME/.local/bin/uv"
            if command -v uvx >/dev/null 2>&1; then
                install -m 0755 "$(command -v uvx)" "$HOME/.local/bin/uvx"
            fi
            fix_root_install_ownership
            BOOTSTRAP_UV_BINARY="$HOME/.local/bin/uv"
        fi
        if [ "$RUNNING_AS_ROOT" = "true" ] && [ "${BOOTSTRAP_UV_BINARY#"$HOME"/}" != "$BOOTSTRAP_UV_BINARY" ]; then
            chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$BOOTSTRAP_UV_BINARY"
            if [ -e "$HOME/.local/bin/uvx" ]; then
                chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" "$HOME/.local/bin/uvx"
            fi
        fi
        return 0
    fi

    echo "[+] Installing uv..."
    if command -v curl > /dev/null 2>&1; then
        if [ "$RUNNING_AS_ROOT" = "true" ]; then
            curl -LsSf https://astral.sh/uv/install.sh | run_as_archivebox_user env UV_NO_MODIFY_PATH=1 sh
        else
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi
    elif command -v wget > /dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | run_as_archivebox_user sh
    else
        echo "[X] curl or wget is required to install uv."
        exit 1
    fi

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv > /dev/null 2>&1; then
        echo "[X] uv was installed, but the uv command was not found in PATH."
        echo "    Add ~/.local/bin to PATH, then run this script again."
        exit 1
    fi
    BOOTSTRAP_UV_BINARY="$(command -v uv)"
    fix_root_install_ownership
}

resolve_setup_binary() {
    local binary_name="$1"
    local binproviders="$2"
    local install_binary="$3"
    local resolved_binary
    local -a abxpkg_args=(
        env
        --json
        "--lib=$ABXPKG_LIB_DIR"
        "--binproviders=$binproviders"
    )
    if [ "$install_binary" = "true" ]; then
        abxpkg_args+=(--install)
    fi
    abxpkg_args+=("$binary_name")

    run_as_archivebox_user "$BOOTSTRAP_UV_BINARY" tool run --from "$ABXPKG_PACKAGE" abxpkg "${abxpkg_args[@]}" >/dev/null

    resolved_binary="$ABXPKG_LIB_DIR/env/bin/$binary_name"
    test -L "$resolved_binary"
    test -x "$resolved_binary"
}

prepare_abxpkg_environment() {
    ensure_uv
    mkdir -p "$ABXPKG_LIB_DIR/env/bin"
    fix_root_install_ownership
    export ABXPKG_LIB_DIR
    export PATH="$ABXPKG_LIB_DIR/env/bin:$PATH"

    resolve_setup_binary uv env false
    UV_BINARY="$ABXPKG_LIB_DIR/env/bin/uv"
    BOOTSTRAP_UV_BINARY="$UV_BINARY"

    if resolve_setup_binary open env false 2>/dev/null; then
        OPEN_BINARY="$ABXPKG_LIB_DIR/env/bin/open"
    fi
    fix_root_install_ownership
}

resolve_setup_curl() {
    resolve_setup_binary curl env,brew,apt true
    CURL_BINARY="$ABXPKG_LIB_DIR/env/bin/curl"
}

install_archivebox_with_uv() {
    echo
    echo "[+] Installing ArchiveBox python tool using uv from $ARCHIVEBOX_PACKAGE..."
    run_as_archivebox_user "$UV_BINARY" --no-config tool install --python "$ARCHIVEBOX_PYTHON" --prerelease explicit --upgrade "$ARCHIVEBOX_PACKAGE"

    uv_tool_bin_dir="$(run_as_archivebox_user "$UV_BINARY" --no-config tool dir --bin)"
    ARCHIVEBOX_BINARY="$uv_tool_bin_dir/archivebox"
    test -x "$ARCHIVEBOX_BINARY"
    if [ "$RUNNING_AS_ROOT" != "true" ]; then
        "$UV_BINARY" --no-config tool update-shell || true
    fi
    fix_root_install_ownership
    if [ "$RUNNING_AS_ROOT" = "true" ]; then
        mkdir -p /usr/local/bin
        ln -sf "$ARCHIVEBOX_BINARY" /usr/local/bin/archivebox
        ARCHIVEBOX_BINARY="/usr/local/bin/archivebox"
    fi
}

select_archivebox_lib_dir() {
    local configured_lib_dir
    configured_lib_dir="$(
        COLUMNS=10000 env -u ABXPKG_LIB_DIR "$ARCHIVEBOX_BINARY" config --get ABXPKG_LIB_DIR \
            | awk '
                !found && /^[[:space:]]*ABXPKG_LIB_DIR[[:space:]]*=/ {
                    value = $0
                    sub(/^[^=]*=[[:space:]]*/, "", value)
                    sub(/^"/, "", value)
                    sub(/"[[:space:]]*$/, "", value)
                    print value
                    found = 1
                }
            '
    )"
    if [ -z "$configured_lib_dir" ]; then
        echo "[X] Could not resolve the ArchiveBox dependency library directory."
        exit 1
    fi

    ABXPKG_LIB_DIR="$configured_lib_dir"
    export ABXPKG_LIB_DIR
    export PATH="$ABXPKG_LIB_DIR/env/bin:$PATH"
    fix_root_install_ownership
}

prepare_abxpkg_environment
DOCKER_IMAGE_READY="false"
for container_engine in docker podman; do
    if ! resolve_setup_binary "$container_engine" env false 2>/dev/null; then
        continue
    fi

    DOCKER_BINARY="$ABXPKG_LIB_DIR/env/bin/$container_engine"
    if docker_pull_archivebox; then
        CONTAINER_ENGINE_NAME="$container_engine"
        case "$container_engine" in
            docker) CONTAINER_ENGINE_LABEL="Docker" ;;
            podman) CONTAINER_ENGINE_LABEL="Podman" ;;
        esac
        DOCKER_IMAGE_READY="true"
        break
    fi
done

if [ "$DOCKER_IMAGE_READY" = "true" ] && "$DOCKER_BINARY" compose version > /dev/null; then
    resolve_setup_curl
    echo "[+] Initializing an ArchiveBox data folder at $ARCHIVEBOX_DATA_DIR using $CONTAINER_ENGINE_LABEL Compose..."
    ensure_archivebox_data_dir || exit 1
    cd "$ARCHIVEBOX_HOME_DIR"
    migrate_legacy_collection_dir
    if [ ! -f docker-compose.yml ]; then
        compose_download="$(mktemp "$ARCHIVEBOX_HOME_DIR/.docker-compose.yml.XXXXXX")"
        if ! "$CURL_BINARY" -fsSL "$ARCHIVEBOX_COMPOSE_URL" -o "$compose_download"; then
            rm -f "$compose_download"
            exit 1
        fi
        mv "$compose_download" docker-compose.yml
        if [ "$RUNNING_AS_ROOT" = "true" ]; then
            chown "$ARCHIVEBOX_SYSTEM_UID:$ARCHIVEBOX_SYSTEM_GID" docker-compose.yml
        fi
    fi
    export ARCHIVEBOX_IMAGE ARCHIVEBOX_PLATFORM
    docker_compose_run_archivebox init
    docker_compose_run_archivebox install
    echo
    echo "[+] Starting ArchiveBox server using: $CONTAINER_ENGINE_NAME compose up -d..."
    "$DOCKER_BINARY" compose up -d
    wait_for_archivebox
    open_archivebox
    echo
    echo "[√] Server started on http://127.0.0.1:8000 and data directory initialized in $ARCHIVEBOX_DATA_DIR. Usage:"
    echo "    cd $ARCHIVEBOX_HOME_DIR"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose ps"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose down"
    echo "    ${FOLLOWUP_SUDO}env ARCHIVEBOX_IMAGE=$ARCHIVEBOX_IMAGE $CONTAINER_ENGINE_NAME compose pull"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose up"
    echo "    Open http://localhost:8000/admin/ to create the first admin and finish web setup."
    echo "    (When running remotely, replace localhost with this server's IP address or hostname.)"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose exec archivebox archivebox add 'https://example.com'"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose exec archivebox archivebox list"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME compose exec archivebox archivebox help"
    exit 0
elif [ "$DOCKER_IMAGE_READY" = "true" ]; then
    resolve_setup_curl
    echo "[+] Initializing an ArchiveBox data folder at $ARCHIVEBOX_DATA_DIR using $CONTAINER_ENGINE_LABEL..."
    ensure_archivebox_data_dir || exit 1
    cd "$ARCHIVEBOX_HOME_DIR"
    migrate_legacy_collection_dir
    cd ./data
    docker_run_archivebox_init
    docker_run_archivebox_install
    echo
    echo "[+] Starting ArchiveBox server using: $CONTAINER_ENGINE_NAME run -d $ARCHIVEBOX_IMAGE..."
    "$DOCKER_BINARY" rm -f archivebox >/dev/null 2>&1 || true
    docker_run_archivebox_server
    wait_for_archivebox
    open_archivebox
    echo
    echo "[√] Server started on http://127.0.0.1:8000 and data directory initialized in $ARCHIVEBOX_DATA_DIR. Usage:"
    echo "    cd $ARCHIVEBOX_DATA_DIR"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME ps --filter name=archivebox"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME rm -f archivebox"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME pull $ARCHIVEBOX_IMAGE"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME run $DOCKER_PLATFORM_ARGS -v $PWD:/data -d -p 8000:8000 --name=archivebox $ARCHIVEBOX_IMAGE"
    echo "    Open http://localhost:8000/admin/ to create the first admin and finish web setup."
    echo "    (When running remotely, replace localhost with this server's IP address or hostname.)"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME run $DOCKER_PLATFORM_ARGS -v $PWD:/data -it $ARCHIVEBOX_IMAGE add 'https://example.com'"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME run $DOCKER_PLATFORM_ARGS -v $PWD:/data -it $ARCHIVEBOX_IMAGE list"
    echo "    ${FOLLOWUP_SUDO}$CONTAINER_ENGINE_NAME run $DOCKER_PLATFORM_ARGS -v $PWD:/data -it $ARCHIVEBOX_IMAGE help"
    exit 0
fi

echo
echo "[!] It's highly recommended to use ArchiveBox with Docker Compose or Podman Compose, but neither container engine is available."
echo
echo "    ⚠️ If you want to use Docker or Podman, press [Ctrl-C] to cancel now. ⚠️"
echo "        Check 'docker info' or 'podman info'. Start the container engine or fix its socket access, then rerun."
echo "        Rerunning with sudo intentionally creates a system-owned deployment under /var/lib/archivebox/archivebox instead of ~/archivebox."
echo "        Install Docker if needed: https://docs.docker.com/get-docker/"
echo
echo "Otherwise, install will continue with uv in 12s... (press [Ctrl+C] to cancel)"
echo
sleep 12 || exit 1
echo "Proceeding with uv..."
echo

echo "[i] ArchiveBox Setup Script 📦"
echo
echo "    This is a helper script which installs ArchiveBox and bootstraps its runtime dependencies."
echo "    You may be prompted for a sudo password in order to install the following:"
echo
echo "        - uv / curl / ca-certificates          (as needed to bootstrap ArchiveBox)"
echo "        - archivebox                           (installed by uv with Python $ARCHIVEBOX_PYTHON)"
echo "        - extractor/plugin dependencies        (installed/discovered by archivebox install)"
echo
echo "    If you'd rather install these manually as-needed, you can find detailed documentation here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Install"
echo
echo "Continuing in 12s... (press [Ctrl+C] to cancel)"
echo
sleep 12 || exit 1
echo "Proceeding to install ArchiveBox..."
echo

echo

resolve_setup_curl
install_archivebox_with_uv

echo
echo "[+] Initializing ArchiveBox data folder at $ARCHIVEBOX_DATA_DIR..."
ensure_archivebox_data_dir || exit 1
cd "$ARCHIVEBOX_HOME_DIR"
migrate_legacy_collection_dir
cd ./data
: | "$ARCHIVEBOX_BINARY" init   # pipe in empty command to make sure stdin is closed
select_archivebox_lib_dir
"$ARCHIVEBOX_BINARY" install
# init shows version output at the end too
echo
echo "[+] Starting ArchiveBox server using: archivebox server --daemonize..."
"$ARCHIVEBOX_BINARY" server --daemonize 0.0.0.0:8000
wait_for_archivebox
open_archivebox
echo
echo "[√] Server started on http://127.0.0.1:8000 and data directory initialized in $ARCHIVEBOX_DATA_DIR. Usage:"
echo "    cd $ARCHIVEBOX_DATA_DIR                            # see your data dir"
echo "    ${FOLLOWUP_SUDO}archivebox server 0.0.0.0:8000                     # start server process"
echo "    Open http://localhost:8000/admin/ to create the first admin and finish web setup."
echo "    (When running remotely, replace localhost with this server's IP address or hostname.)"
echo "    ps aux | grep archivebox                           # see server process pid"
echo "    ${FOLLOWUP_SUDO}pkill -f 'archivebox server'                       # stop the server"
echo "    curl -fsSL 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh' | ${FOLLOWUP_SUDO}bash  # update versions"
echo "    ${FOLLOWUP_SUDO}archivebox add 'https://example.com'"              # archive a new URL
echo "    ${FOLLOWUP_SUDO}archivebox list                                    # see URLs archived"
echo "    ${FOLLOWUP_SUDO}archivebox help                                    # see more help & examples"
