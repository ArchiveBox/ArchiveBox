#!/usr/bin/env bash

set -o errexit
set -o errtrace
set -o nounset
set -o pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${UI_SCREENSHOT_DATA_DIR:-$REPO_DIR/data}"
OUTPUT_DIR="${UI_SCREENSHOT_OUTPUT_DIR:-$REPO_DIR/docs/screenshots}"
PUBLIC_OUTPUT_DIR="${UI_SCREENSHOT_PUBLIC_OUTPUT_DIR:-$REPO_DIR/publicsite/screenshots}"
REQUESTED_PORT="${UI_SCREENSHOT_PORT:-}"
MAX_VIEWS="${UI_SCREENSHOT_MAX_VIEWS:-0}"
USERNAME="archivebox-screenshots-$$"
PASSWORD="archivebox-screenshots-$$"
SERVER_PID=""
SETUP_SERVER_PID=""
ARCHIVE_PID=""
CREATED_TEMP_USER=0
CREATE_API_TOKEN=0
CREATE_WEBHOOK=0
ABXPKG_LIB_DIR=""
SCREENSHOT_CHROME_BINARY=""
CAPTURE_ROOT="$(mktemp -d)"
MANIFEST_FILE="$CAPTURE_ROOT/manifest.jsonl"
PERSONAS_DIR="$CAPTURE_ROOT/personas"
ACTIVE_PERSONA="Screenshots"
CAPTURE_PROFILES=$'desktop|1600|1000\ntablet|1024|1366\nmobile|390|844'

stop_background_runner() {
    (
        cd "$DATA_DIR"
        uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
            'from archivebox.workers.supervisord_util import get_existing_supervisord_process, stop_worker; supervisor=get_existing_supervisord_process(quiet=True); supervisor is not None and stop_worker(supervisor, "worker_runner")'
    ) >/dev/null
}

cleanup() {
    if [[ -n "$SETUP_SERVER_PID" ]]; then
        setup_server_children="$(pgrep -P "$SETUP_SERVER_PID" 2>/dev/null || true)"
        for child_pid in $setup_server_children; do
            kill "$child_pid" 2>/dev/null || true
        done
        kill "$SETUP_SERVER_PID" 2>/dev/null || true
        for _attempt in $(seq 1 50); do
            setup_server_running=0
            kill -0 "$SETUP_SERVER_PID" 2>/dev/null && setup_server_running=1
            for child_pid in $setup_server_children; do
                kill -0 "$child_pid" 2>/dev/null && setup_server_running=1
            done
            [[ "$setup_server_running" == "0" ]] && break
            sleep 0.1
        done
        for child_pid in $setup_server_children; do
            kill -KILL "$child_pid" 2>/dev/null || true
        done
        kill -KILL "$SETUP_SERVER_PID" 2>/dev/null || true
        wait "$SETUP_SERVER_PID" 2>/dev/null || true
    fi

    if [[ -n "$ARCHIVE_PID" ]] && kill -0 "$ARCHIVE_PID" 2>/dev/null; then
        archive_children="$(pgrep -P "$ARCHIVE_PID" 2>/dev/null || true)"
        for child_pid in $archive_children; do
            kill "$child_pid" 2>/dev/null || true
        done
        kill "$ARCHIVE_PID" 2>/dev/null || true
        for _attempt in $(seq 1 50); do
            archive_running=0
            kill -0 "$ARCHIVE_PID" 2>/dev/null && archive_running=1
            for child_pid in $archive_children; do
                kill -0 "$child_pid" 2>/dev/null && archive_running=1
            done
            [[ "$archive_running" == "0" ]] && break
            sleep 0.1
        done
        for child_pid in $archive_children; do
            kill -KILL "$child_pid" 2>/dev/null || true
        done
        kill -KILL "$ARCHIVE_PID" 2>/dev/null || true
        wait "$ARCHIVE_PID" 2>/dev/null || true
    fi
    if [[ -n "$SERVER_PID" ]]; then
        server_children="$(pgrep -P "$SERVER_PID" 2>/dev/null || true)"
        for child_pid in $server_children; do
            kill "$child_pid" 2>/dev/null || true
        done
        kill "$SERVER_PID" 2>/dev/null || true
        for _attempt in $(seq 1 50); do
            server_running=0
            kill -0 "$SERVER_PID" 2>/dev/null && server_running=1
            for child_pid in $server_children; do
                kill -0 "$child_pid" 2>/dev/null && server_running=1
            done
            [[ "$server_running" == "0" ]] && break
            sleep 0.1
        done
        for child_pid in $server_children; do
            kill -KILL "$child_pid" 2>/dev/null || true
        done
        kill -KILL "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi

    if [[ "$CREATED_TEMP_USER" == "1" && -f "$DATA_DIR/index.sqlite3" ]]; then
        (
            cd "$DATA_DIR"
            UI_SCREENSHOT_USERNAME="$USERNAME" uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                'import os; from django.contrib.auth import get_user_model; get_user_model().objects.filter(username=os.environ["UI_SCREENSHOT_USERNAME"]).delete()'
        ) >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT INT TERM

mkdir -p "$DATA_DIR" "$OUTPUT_DIR" "$PUBLIC_OUTPUT_DIR"

echo "[*] Initializing the ArchiveBox collection at $DATA_DIR"
(
    cd "$DATA_DIR"
    uv run --no-cache --project "$REPO_DIR" archivebox init --quick
    uv run --no-cache --project "$REPO_DIR" archivebox install
)

SEED_STATE="$( (
    cd "$DATA_DIR"
    uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
        'from django.db.models import Count; from archivebox.core.models import Snapshot, ArchiveResult; from archivebox.crawls.models import CrawlSchedule; from archivebox.personas.models import Persona; from archivebox.api.models import APIToken; from signal_webhooks.utils import get_webhook_model; recent=list(Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED).order_by("-bookmarked_at").values_list("id", "status")[:100]); counts=dict(ArchiveResult.objects.filter(snapshot_id__in=[row[0] for row in recent], status="succeeded").values_list("snapshot_id").annotate(Count("id"))); screenshots=set(ArchiveResult.objects.filter(snapshot_id__in=[row[0] for row in recent], plugin="screenshot", status="succeeded").values_list("snapshot_id", flat=True)); useful=sum(counts.get(snapshot_id,0)>=8 and snapshot_id in screenshots for snapshot_id,status in recent)>=2; print(int(useful)); print(CrawlSchedule.objects.count()); print(Persona.objects.exclude(name="Default").count()); print(APIToken.objects.count()); print(get_webhook_model().objects.count())'
) | tail -5)"
HAS_USEFUL_SNAPSHOT="$(printf '%s\n' "$SEED_STATE" | sed -n '1p')"
HAS_SCHEDULE="$(printf '%s\n' "$SEED_STATE" | sed -n '2p')"
HAS_PERSONA="$(printf '%s\n' "$SEED_STATE" | sed -n '3p')"
HAS_API_TOKEN="$(printf '%s\n' "$SEED_STATE" | sed -n '4p')"
HAS_WEBHOOK="$(printf '%s\n' "$SEED_STATE" | sed -n '5p')"

if [[ "$HAS_USEFUL_SNAPSHOT" == "0" ]]; then
    echo "[*] Archiving real reference sites so snapshot views have meaningful outputs"
    (
        cd "$DATA_DIR"
        uv run --no-cache --project "$REPO_DIR" archivebox add \
            --depth=0 \
            --overwrite \
            --tag=documentation,reference \
            --plugins=title,headers,wget,screenshot,pdf,dom,readability,htmltotext,hashes,dns \
            https://example.com https://archivebox.io
    )
fi

if [[ "$HAS_SCHEDULE" == "0" ]]; then
    echo "[*] Creating a real weekly documentation crawl schedule"
    (
        cd "$DATA_DIR"
        uv run --no-cache --project "$REPO_DIR" archivebox schedule --every=weekly --depth=0 --tag=documentation https://archivebox.io/feed.xml
    )
fi

if [[ "$HAS_PERSONA" == "0" ]]; then
    echo "[*] Creating a real browser persona for the populated Persona views"
    (
        cd "$DATA_DIR"
        uv run --no-cache --project "$REPO_DIR" archivebox persona create "Research Browser"
    )
fi

[[ "$HAS_API_TOKEN" == "0" ]] && CREATE_API_TOKEN=1
[[ "$HAS_WEBHOOK" == "0" ]] && CREATE_WEBHOOK=1

ROUTE_CONFIG="$( (
    cd "$DATA_DIR"
    uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
        'from urllib.parse import urlparse; from archivebox.config.common import get_config; from archivebox.core.routes_util import get_admin_base_url, get_web_base_url; config = get_config(); admin = get_admin_base_url(config=config); web = get_web_base_url(config=config); admin_parsed = urlparse(admin); web_parsed = urlparse(web); print(admin); print(web); print(admin_parsed.port or (443 if admin_parsed.scheme == "https" else 80)); print(admin_parsed.hostname or ""); print(web_parsed.hostname or "")'
) | tail -5)"
ADMIN_BASE_URL="$(printf '%s\n' "$ROUTE_CONFIG" | sed -n '1p')"
PUBLIC_BASE_URL="$(printf '%s\n' "$ROUTE_CONFIG" | sed -n '2p')"
PORT="$(printf '%s\n' "$ROUTE_CONFIG" | sed -n '3p')"
ADMIN_HOST="$(printf '%s\n' "$ROUTE_CONFIG" | sed -n '4p')"
PUBLIC_HOST="$(printf '%s\n' "$ROUTE_CONFIG" | sed -n '5p')"
SCREENSHOT_HOST_RESOLVER_RULES="${SCREENSHOT_HOST_RESOLVER_RULES:-MAP $ADMIN_HOST 127.0.0.1,MAP $PUBLIC_HOST 127.0.0.1}"
export SCREENSHOT_HOST_RESOLVER_RULES

if [[ -n "$REQUESTED_PORT" && "$REQUESTED_PORT" != "$PORT" ]]; then
    echo "[!] UI_SCREENSHOT_PORT=$REQUESTED_PORT conflicts with the canonical admin origin $ADMIN_BASE_URL" >&2
    echo "[!] Update BASE_URL/BIND_ADDR together instead of capturing a login form on an origin that cannot submit it." >&2
    exit 1
fi

echo "[*] Creating a temporary screenshot admin"
(
    cd "$DATA_DIR"
    uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
        'from django.contrib.auth import get_user_model; get_user_model().objects.filter(username__startswith="archivebox-screenshots-").delete()'
    UI_SCREENSHOT_USERNAME="$USERNAME" UI_SCREENSHOT_PASSWORD="$PASSWORD" \
        uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
        'import os; from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser(username=os.environ["UI_SCREENSHOT_USERNAME"], password=os.environ["UI_SCREENSHOT_PASSWORD"])'
)
CREATED_TEMP_USER=1

echo "[*] Starting ArchiveBox on port $PORT"
(
    cd "$DATA_DIR"
    # Use the real server command so the runner, worker, and log views describe
    # the same persistent runtime that an operator sees.
    UI_SCREENSHOT_HIDE_HIGH_LOAD_WARNING=1 \
        exec uv run --no-cache --project "$REPO_DIR" archivebox server "127.0.0.1:$PORT"
) >"$DATA_DIR/ui-screenshot-server.log" 2>&1 &
SERVER_PID=$!

ready=0
for _attempt in $(seq 1 60); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[!] ArchiveBox exited before becoming ready" >&2
        tail -100 "$DATA_DIR/ui-screenshot-server.log" >&2
        exit 1
    fi
    if curl --fail --silent --show-error --resolve "$ADMIN_HOST:$PORT:127.0.0.1" "$ADMIN_BASE_URL/admin/login/" >/dev/null; then
        ready=1
        break
    fi
    sleep 1
done

if [[ "$ready" != "1" ]]; then
    echo "[!] ArchiveBox did not become ready within 60 seconds" >&2
    tail -100 "$DATA_DIR/ui-screenshot-server.log" >&2
    exit 1
fi

# The persistent collection can contain old runnable work unrelated to this
# gallery. Keep the real server stack, but stop its general queue consumer;
# the Sweeting.me example below runs through its own real foreground runner.
stop_background_runner

ABXPKG_LIB_DIR="$(uv run --no-cache --project "$REPO_DIR" abx-dl config --get ABXPKG_LIB_DIR | sed 's/^[^=]*=//; s/^"//; s/"$//')"
SCREENSHOT_CHROME_BINARY="$ABXPKG_LIB_DIR/env/bin/chromium"
if [[ ! -x "$SCREENSHOT_CHROME_BINARY" ]]; then
    echo "[!] abx-dl projected Chromium was not found at $SCREENSHOT_CHROME_BINARY" >&2
    exit 1
fi

VIEWS=(
    "First-time setup wizard|setup-wizard://admin/|/admin/|archivebox/templates/core/setup_wizard.html|setup-wizard"
    "Login|$ADMIN_BASE_URL/admin/login/|/admin/login/|archivebox/templates/admin/login.html"
    "Public snapshot list|$PUBLIC_BASE_URL/public/|/public/|archivebox/core/views.py"
)

capture_index=0
while [[ "$capture_index" -lt "${#VIEWS[@]}" ]]; do
    view="${VIEWS[$capture_index]}"
    IFS='|' read -r name url expected_path source capture_mode <<<"$view"
    capture_index=$((capture_index + 1))
    slug="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | sed 's/^-//; s/-$//')"
    expected_plugin=""
    if [[ "$name" == "Snapshot View ("*")" && "$capture_mode" != "live-progress" && "$capture_mode" != "snapshot-collapsed" ]]; then
        expected_plugin="${name#Snapshot View (}"
        expected_plugin="${expected_plugin%)}"
    fi

    echo "[*] $name: $url"
    if [[ "$capture_mode" == "snapshot-collapsed" ]]; then
        NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
            CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
            SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
            SCREENSHOT_SNAPSHOT_HEADER=collapsed \
            SCREENSHOT_WIDTH=1600 \
            SCREENSHOT_HEIGHT=1000 \
            node "$REPO_DIR/bin/take_screenshot.js" "$url" "$CAPTURE_ROOT/snapshot-header-state.png" >/dev/null
    fi
    view_timing_report=""
    while IFS='|' read -r profile viewport_width viewport_height; do
        filename="$(printf '%02d' "$capture_index")-$slug-$profile.png"
        capture_dir="$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/$profile"
        timing_report_path="$view_timing_report"
        capture_env=(
            "RESOLUTION=$viewport_width,$viewport_height"
            "CHROME_RESOLUTION=$viewport_width,$viewport_height"
            "PERSONAS_DIR=$PERSONAS_DIR"
            "ACTIVE_PERSONA=$ACTIVE_PERSONA"
            "SCREENSHOT_RESOLUTION=$viewport_width,$viewport_height"
            "SCREENSHOT_TIMEOUT=120"
            "CHROME_WAIT_FOR=load"
            "SCREENSHOT_COLLAPSE_FILTERS=1"
        )
        if [[ "$capture_mode" == wait-replay:* ]]; then
            capture_env+=(
                "SCREENSHOT_WAIT_FOR_TEXT=${capture_mode#wait-replay:}"
                "SCREENSHOT_WAIT_FOR_FRAME_URL=/replay/w/"
            )
        elif [[ "$capture_mode" == wait-text:* ]]; then
            capture_env+=(
                "CHROME_WAIT_FOR=domcontentloaded"
                "SCREENSHOT_WAIT_FOR_TEXT=${capture_mode#wait-text:}"
            )
        fi

        screenshot_path=""
        if [[ "$capture_mode" == "setup-wizard" ]]; then
            screenshot_path="$capture_dir/screenshot.png"
            if [[ "$profile" == "desktop" ]]; then
                SETUP_DATA_DIR="$CAPTURE_ROOT/setup-wizard-data"
                SETUP_PORT="$(uv run --no-cache --project "$REPO_DIR" python - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
                SETUP_BASE_URL="http://archivebox.localhost:$SETUP_PORT"
                SETUP_HOST_RESOLVER_RULES="MAP archivebox.localhost 127.0.0.1"
                mkdir -p "$SETUP_DATA_DIR" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile"
                (
                    cd "$SETUP_DATA_DIR"
                    BASE_URL= uv run --no-cache --project "$REPO_DIR" archivebox init --quick
                    UI_SCREENSHOT_USERNAME="$USERNAME" UI_SCREENSHOT_PASSWORD="$PASSWORD" \
                        BASE_URL= uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                        'import os; from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser(username=os.environ["UI_SCREENSHOT_USERNAME"], password=os.environ["UI_SCREENSHOT_PASSWORD"])'
                )
                (
                    cd "$SETUP_DATA_DIR"
                    BASE_URL= UI_SCREENSHOT_HIDE_HIGH_LOAD_WARNING=1 \
                        exec uv run --no-cache --project "$REPO_DIR" archivebox server "127.0.0.1:$SETUP_PORT"
                ) >"$SETUP_DATA_DIR/ui-screenshot-setup-wizard-server.log" 2>&1 &
                SETUP_SERVER_PID=$!
                setup_ready=0
                for _setup_attempt in $(seq 1 60); do
                    if ! kill -0 "$SETUP_SERVER_PID" 2>/dev/null; then
                        echo "[!] Setup-wizard ArchiveBox exited before becoming ready" >&2
                        tail -100 "$SETUP_DATA_DIR/ui-screenshot-setup-wizard-server.log" >&2
                        exit 1
                    fi
                    if curl --fail --silent --show-error --resolve "archivebox.localhost:$SETUP_PORT:127.0.0.1" "$SETUP_BASE_URL/admin/login/" >/dev/null; then
                        setup_ready=1
                        break
                    fi
                    sleep 1
                done
                if [[ "$setup_ready" != "1" ]]; then
                    echo "[!] Setup-wizard ArchiveBox did not become ready within 60 seconds" >&2
                    tail -100 "$SETUP_DATA_DIR/ui-screenshot-setup-wizard-server.log" >&2
                    exit 1
                fi
                setup_variants="$(printf \
                    '[{"path":"%s","width":1600,"height":1000},{"path":"%s","width":1024,"height":1366},{"path":"%s","width":390,"height":844}]' \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile/screenshot.png")"
                NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
                    CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
                    SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/setup-wizard/chrome_profile" \
                    SCREENSHOT_LOGIN_USERNAME="$USERNAME" \
                    SCREENSHOT_LOGIN_PASSWORD="$PASSWORD" \
                    SCREENSHOT_WIDTH=1600 \
                    SCREENSHOT_HEIGHT=1000 \
                    SCREENSHOT_VARIANTS_JSON="$setup_variants" \
                    SCREENSHOT_WAIT_SELECTOR="#archivebox-setup-wizard" \
                    SCREENSHOT_HOST_RESOLVER_RULES="$SETUP_HOST_RESOLVER_RULES" \
                    node "$REPO_DIR/bin/take_screenshot.js" "$SETUP_BASE_URL/admin/login/?next=/admin/" "$screenshot_path" >"$capture_dir/report.json"
                url="$SETUP_BASE_URL/admin/"
                view_timing_report="$capture_dir/report.json"
                timing_report_path="$view_timing_report"
                kill "$SETUP_SERVER_PID" 2>/dev/null || true
                wait "$SETUP_SERVER_PID" 2>/dev/null || true
                SETUP_SERVER_PID=""
            fi
        elif [[ "$capture_mode" == "live-progress" ]]; then
            screenshot_path="$capture_dir/screenshot.png"
            if [[ "$profile" == "desktop" ]]; then
                mkdir -p \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile"
                live_variants="$(printf \
                    '[{"path":"%s","width":1600,"height":1000},{"path":"%s","width":1024,"height":1366},{"path":"%s","width":390,"height":844}]' \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile/screenshot.png")"
                NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
                    CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
                    SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
                    SCREENSHOT_WIDTH=1600 \
                    SCREENSHOT_HEIGHT=1000 \
                    SCREENSHOT_VARIANTS_JSON="$live_variants" \
                    SCREENSHOT_SNAPSHOT_HEADER=expanded \
                    SCREENSHOT_EXPECT_LIVE_PROGRESS=1 \
                    node "$REPO_DIR/bin/take_screenshot.js" "$url" "$screenshot_path" >"$capture_dir/report.json"
                view_timing_report="$capture_dir/report.json"
                timing_report_path="$view_timing_report"
            fi
        elif [[ -n "$expected_plugin" && "$capture_mode" != wait-replay:* ]]; then
            screenshot_path="$capture_dir/screenshot.png"
            if [[ "$profile" == "desktop" ]]; then
                mkdir -p \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile"
                output_variants="$(printf \
                    '[{"path":"%s","width":1600,"height":1000},{"path":"%s","width":1024,"height":1366},{"path":"%s","width":390,"height":844}]' \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/desktop/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/tablet/screenshot.png" \
                    "$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile/screenshot.png")"
                NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
                    CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
                    SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
                    SCREENSHOT_WIDTH=1600 \
                    SCREENSHOT_HEIGHT=1000 \
                    SCREENSHOT_VARIANTS_JSON="$output_variants" \
                    SCREENSHOT_COLLAPSE_FILTERS=1 \
                    SCREENSHOT_EXPECT_PLUGIN="$expected_plugin" \
                    node "$REPO_DIR/bin/take_screenshot.js" "$url" "$screenshot_path" >"$capture_dir/report.json"
                view_timing_report="$capture_dir/report.json"
                timing_report_path="$view_timing_report"
                uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py" validate \
                    "$capture_dir/report.json" "$expected_path"
            fi
        elif [[ "$profile" == "desktop" || "$capture_mode" == wait-replay:* || -z "${ABXPKG_LIB_DIR:-}" ]]; then
            capture_log="$CAPTURE_ROOT/$(printf '%02d' "$capture_index")-$profile-abx-dl.log"
            if ! env "${capture_env[@]}" uv run --no-cache --project "$REPO_DIR" abx-dl dl \
                --plugins=screenshot \
                --timeout=120 \
                --dir "$capture_dir" \
                "$url" >"$capture_log" 2>&1; then
                echo "[!] abx-dl failed while capturing $profile $url" >&2
                tail -100 "$capture_log" >&2
                exit 1
            fi

            screenshot_path="$(find "$capture_dir" -type f -path '*/screenshot/screenshot.png' -print -quit)"
            screenshot_metadata_path="$(find "$capture_dir" -type f -path '*/screenshot/screenshot.json' -print -quit)"
            if [[ -z "$screenshot_metadata_path" || ! -s "$screenshot_metadata_path" ]]; then
                echo "[!] Screenshot navigation metadata is missing for $profile $url" >&2
                tail -100 "$capture_log" >&2
                exit 1
            fi
            uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py" validate \
                "$screenshot_metadata_path" "$expected_path"
        else
            screenshot_path="$capture_dir/screenshot.png"
            if [[ "$profile" == "tablet" ]]; then
                mobile_capture_dir="$CAPTURE_ROOT/$(printf '%02d' "$capture_index")/mobile"
                mkdir -p "$capture_dir" "$mobile_capture_dir"
                responsive_variants="$(printf \
                    '[{"path":"%s","width":1024,"height":1366},{"path":"%s","width":390,"height":844}]' \
                    "$capture_dir/screenshot.png" \
                    "$mobile_capture_dir/screenshot.png")"
                NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
                    CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
                    SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
                    SCREENSHOT_WIDTH=1024 \
                    SCREENSHOT_HEIGHT=1366 \
                    SCREENSHOT_VARIANTS_JSON="$responsive_variants" \
                    SCREENSHOT_COLLAPSE_FILTERS=1 \
                    SCREENSHOT_EXPECT_PLUGIN="$expected_plugin" \
                    node "$REPO_DIR/bin/take_screenshot.js" "$url" "$screenshot_path" >"$capture_dir/report.json"
                view_timing_report="$capture_dir/report.json"
                timing_report_path="$view_timing_report"
                uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py" validate \
                    "$capture_dir/report.json" "$expected_path"
            fi
        fi
        if [[ -z "$screenshot_path" || ! -s "$screenshot_path" ]]; then
            echo "[!] Screenshot plugin did not produce a $profile PNG for $url" >&2
            [[ -n "${capture_log:-}" && -f "$capture_log" ]] && tail -100 "$capture_log" >&2
            exit 1
        fi
        cp "$screenshot_path" "$OUTPUT_DIR/$filename"
        cp "$screenshot_path" "$PUBLIC_OUTPUT_DIR/$filename"
        UI_SCREENSHOT_NAME="$name" UI_SCREENSHOT_URL="$url" UI_SCREENSHOT_SOURCE="$source" \
            UI_SCREENSHOT_FILENAME="$filename" UI_SCREENSHOT_PROFILE="$profile" \
            UI_SCREENSHOT_TIMING_REPORT="$timing_report_path" \
            uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py" append \
                "$MANIFEST_FILE" "$OUTPUT_DIR/$filename"
    done <<<"$CAPTURE_PROFILES"

    # Capture the public views before login because the real admin-login hint
    # intentionally redirects authenticated personas away from /public/.
    if [[ "$name" == "Public snapshot list" ]]; then
        echo "[*] Logging in through the real $ACTIVE_PERSONA browser persona"
        NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
            CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
            SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
            SCREENSHOT_LOGIN_USERNAME="$USERNAME" \
            SCREENSHOT_LOGIN_PASSWORD="$PASSWORD" \
            SCREENSHOT_WIDTH=1600 \
            SCREENSHOT_HEIGHT=1000 \
            SCREENSHOT_COLLAPSE_FILTERS=1 \
            node "$REPO_DIR/bin/take_screenshot.js" "$ADMIN_BASE_URL/admin/login/" "$CAPTURE_ROOT/persona-login.png" >/dev/null

        echo "[*] Populating empty configuration views through the real Django admin UI"
        NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
            CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
            SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
            CREATE_API_TOKEN="$CREATE_API_TOKEN" \
            CREATE_WEBHOOK="$CREATE_WEBHOOK" \
            node "$REPO_DIR/bin/setup_ui_screenshot_data.js" "$ADMIN_BASE_URL" "$USERNAME"

        OPENCODE_PORT="$(uv run --no-cache --project "$REPO_DIR" python - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
        (
            cd "$DATA_DIR"
            OPENCODE_PORT="$OPENCODE_PORT" uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                'import os; from archivebox.machine.models import Machine; Machine.from_json({"config": {"OPENCODE_ENABLED": True, "OPENCODE_PORT": int(os.environ["OPENCODE_PORT"])}})'
            uv run --no-cache --project "$REPO_DIR" archivebox install opencode --binproviders=env,pnpm
        )

        SWEETING_CAPTURE_STARTED_AT="$( (
            cd "$DATA_DIR"
            uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                'from django.utils import timezone; print(timezone.now().isoformat())'
        ) | tail -1)"
        echo "[*] Starting a real Sweeting.me capture for the live progress view"
        (
            cd "$DATA_DIR"
            exec uv run --no-cache --project "$REPO_DIR" archivebox add \
                --depth=0 \
                --overwrite \
                --tag=screenshot-gallery \
                https://sweeting.me
        ) >"$CAPTURE_ROOT/sweeting-live-capture.log" 2>&1 &
        ARCHIVE_PID=$!

        LIVE_SNAPSHOT_VIEW_URL=""
        for _attempt in $(seq 1 120); do
            LIVE_SNAPSHOT_RECORD="$( (
                cd "$DATA_DIR"
                UI_SCREENSHOT_CAPTURE_STARTED_AT="$SWEETING_CAPTURE_STARTED_AT" uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                    'import os; from django.utils.dateparse import parse_datetime; from archivebox.core.models import Snapshot; from archivebox.core.routes_util import build_snapshot_url; started_at=parse_datetime(os.environ["UI_SCREENSHOT_CAPTURE_STARTED_AT"]); snapshot=Snapshot.objects.filter(url__startswith="https://sweeting.me",bookmarked_at__gte=started_at).order_by("-bookmarked_at").first(); print(build_snapshot_url(str(snapshot.id), "") if snapshot else "")'
            ) | tail -1)"
            if [[ -n "$LIVE_SNAPSHOT_RECORD" ]]; then
                LIVE_SNAPSHOT_VIEW_URL="$LIVE_SNAPSHOT_RECORD"
                break
            fi
            if ! kill -0 "$ARCHIVE_PID" 2>/dev/null; then
                echo "[!] Sweeting.me capture exited before creating a snapshot" >&2
                tail -100 "$CAPTURE_ROOT/sweeting-live-capture.log" >&2
                exit 1
            fi
            sleep 1
        done
        if [[ -z "$LIVE_SNAPSHOT_VIEW_URL" ]]; then
            echo "[!] Timed out waiting for the live Sweeting.me snapshot" >&2
            exit 1
        fi
        VIEWS+=(
            "Snapshot View (capture in progress)|$LIVE_SNAPSHOT_VIEW_URL|/|archivebox/templates/core/snapshot.html|live-progress"
        )

        RECORD_CONFIG="$( (
            cd "$DATA_DIR"
            uv run --no-cache --project "$REPO_DIR" archivebox manage shell --no-imports -c \
                'from django.db.models import Count; from archivebox.core.models import Snapshot, ArchiveResult, Tag; from archivebox.crawls.models import Crawl, CrawlSchedule; from archivebox.personas.models import Persona; from archivebox.machine.models import Machine, NetworkInterface, Binary, Process; from archivebox.api.models import APIToken; from django.contrib.auth import get_user_model; from signal_webhooks.utils import get_webhook_model; from archivebox.core.routes_util import build_snapshot_url; recent=list(Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED).order_by("-bookmarked_at").values_list("id", flat=True)[:1000]); counts=dict(ArchiveResult.objects.filter(snapshot_id__in=recent,status="succeeded").values_list("snapshot_id").annotate(Count("id"))); snapshot_id=str(max(recent,key=lambda item: counts.get(item,0))); snapshot=Snapshot.objects.get(id=snapshot_id); result=ArchiveResult.objects.filter(snapshot_id=snapshot_id,status="succeeded").order_by("-output_size").first() or ArchiveResult.objects.filter(snapshot_id=snapshot_id).first(); tag=snapshot.tags.first() or Tag.objects.first(); crawl=snapshot.crawl or Crawl.objects.order_by("-created_at").first(); schedule=CrawlSchedule.objects.order_by("-created_at").first(); persona=Persona.objects.exclude(name="Default").order_by("-created_at").first() or Persona.objects.first(); machine=Machine.objects.order_by("-modified_at").first(); interface=NetworkInterface.objects.order_by("-modified_at").first(); binary=Binary.objects.order_by("-modified_at").first(); process=Process.objects.order_by("-created_at").first(); token=APIToken.objects.order_by("-created_at").first(); webhook=get_webhook_model().objects.order_by("-created_at").first(); user=get_user_model().objects.get(username="'"$USERNAME"'"); values={"SNAPSHOT_ID":snapshot_id,"SNAPSHOT_VIEW_URL":build_snapshot_url(snapshot_id,""),"SNAPSHOT_FILES_URL":build_snapshot_url(snapshot_id,"/?files=1"),"ARCHIVERESULT_ID":str(result.id),"TAG_ID":str(tag.id),"USER_ID":str(user.id),"CRAWL_ID":str(crawl.id),"SCHEDULE_ID":str(schedule.id),"PERSONA_ID":str(persona.id),"MACHINE_ID":str(machine.id),"INTERFACE_ID":str(interface.id),"BINARY_ID":str(binary.id),"PROCESS_ID":str(process.id),"TOKEN_ID":str(token.id),"WEBHOOK_ID":str(webhook.id)}; [print(f"{key}={value}") for key,value in values.items()]'
        ) | tail -15)"
        eval "$RECORD_CONFIG"

        VIEWS+=(
            "Add URLs|$ADMIN_BASE_URL/add/|/add/|archivebox/core/views.py"
            "Admin dashboard|$ADMIN_BASE_URL/admin/|/admin/|archivebox/core/admin_site.py"
            "AI agent|$ADMIN_BASE_URL/admin/agent/|/admin/agent/|abx_plugins/plugins/opencode/views.py|wait-text:ArchiveBox AI Agent"
            "Snapshots table|$ADMIN_BASE_URL/admin/core/snapshot/|/admin/core/snapshot/|archivebox/core/admin_snapshots.py"
            "Snapshots grid|$ADMIN_BASE_URL/admin/core/snapshot/grid/|/admin/core/snapshot/grid/|archivebox/templates/admin/snapshots_grid.html"
            "Snapshot admin detail|$ADMIN_BASE_URL/admin/core/snapshot/$SNAPSHOT_ID/change/|/admin/core/snapshot/$SNAPSHOT_ID/change/|archivebox/core/admin_snapshots.py"
            "Snapshot files|$SNAPSHOT_FILES_URL|/|archivebox/templates/core/static_index.html"
            "Archive results|$ADMIN_BASE_URL/admin/core/archiveresult/|/admin/core/archiveresult/|archivebox/core/admin_archiveresults.py"
            "Archive result detail|$ADMIN_BASE_URL/admin/core/archiveresult/$ARCHIVERESULT_ID/change/|/admin/core/archiveresult/$ARCHIVERESULT_ID/change/|archivebox/core/admin_archiveresults.py"
            "Tags|$ADMIN_BASE_URL/admin/core/tag/|/admin/core/tag/|archivebox/core/admin_tags.py"
            "Tag detail|$ADMIN_BASE_URL/admin/core/tag/$TAG_ID/change/|/admin/core/tag/$TAG_ID/change/|archivebox/core/admin_tags.py"
            "Users|$ADMIN_BASE_URL/admin/auth/user/|/admin/auth/user/|archivebox/core/admin_users.py"
            "User detail|$ADMIN_BASE_URL/admin/auth/user/$USER_ID/change/|/admin/auth/user/$USER_ID/change/|archivebox/core/admin_users.py"
            "Crawls|$ADMIN_BASE_URL/admin/crawls/crawl/|/admin/crawls/crawl/|archivebox/crawls/admin.py"
            "Crawl detail|$ADMIN_BASE_URL/admin/crawls/crawl/$CRAWL_ID/change/|/admin/crawls/crawl/$CRAWL_ID/change/|archivebox/crawls/admin.py"
            "Crawl schedules|$ADMIN_BASE_URL/admin/crawls/crawlschedule/|/admin/crawls/crawlschedule/|archivebox/crawls/admin.py"
            "Crawl schedule detail|$ADMIN_BASE_URL/admin/crawls/crawlschedule/$SCHEDULE_ID/change/|/admin/crawls/crawlschedule/$SCHEDULE_ID/change/|archivebox/crawls/admin.py"
            "Personas|$ADMIN_BASE_URL/admin/personas/persona/|/admin/personas/persona/|archivebox/personas/admin.py"
            "Persona detail|$ADMIN_BASE_URL/admin/personas/persona/$PERSONA_ID/change/|/admin/personas/persona/$PERSONA_ID/change/|archivebox/personas/admin.py"
            "Machines|$ADMIN_BASE_URL/admin/machine/machine/|/admin/machine/machine/|archivebox/machine/admin.py"
            "Machine detail|$ADMIN_BASE_URL/admin/machine/machine/$MACHINE_ID/change/|/admin/machine/machine/$MACHINE_ID/change/|archivebox/machine/admin.py"
            "Network interfaces|$ADMIN_BASE_URL/admin/machine/networkinterface/|/admin/machine/networkinterface/|archivebox/machine/admin.py"
            "Network interface detail|$ADMIN_BASE_URL/admin/machine/networkinterface/$INTERFACE_ID/change/|/admin/machine/networkinterface/$INTERFACE_ID/change/|archivebox/machine/admin.py"
            "Binaries|$ADMIN_BASE_URL/admin/machine/binary/|/admin/machine/binary/|archivebox/machine/admin.py"
            "Binary detail|$ADMIN_BASE_URL/admin/machine/binary/$BINARY_ID/change/|/admin/machine/binary/$BINARY_ID/change/|archivebox/machine/admin.py"
            "Processes|$ADMIN_BASE_URL/admin/machine/process/|/admin/machine/process/|archivebox/machine/admin.py"
            "Process detail|$ADMIN_BASE_URL/admin/machine/process/$PROCESS_ID/change/|/admin/machine/process/$PROCESS_ID/change/|archivebox/machine/admin.py"
            "API tokens|$ADMIN_BASE_URL/admin/api/apitoken/|/admin/api/apitoken/|archivebox/api/admin.py"
            "API token detail|$ADMIN_BASE_URL/admin/api/apitoken/$TOKEN_ID/change/|/admin/api/apitoken/$TOKEN_ID/change/|archivebox/api/admin.py"
            "Webhooks|$ADMIN_BASE_URL/admin/api/outboundwebhook/|/admin/api/outboundwebhook/|archivebox/api/admin.py"
            "Webhook detail|$ADMIN_BASE_URL/admin/api/outboundwebhook/$WEBHOOK_ID/change/|/admin/api/outboundwebhook/$WEBHOOK_ID/change/|archivebox/api/admin.py"
            "Environment|$ADMIN_BASE_URL/admin/environment/|/admin/environment/|archivebox/core/settings.py"
            "Configuration|$ADMIN_BASE_URL/admin/environment/config/|/admin/environment/config/|archivebox/core/views.py"
            "Configuration detail|$ADMIN_BASE_URL/admin/environment/config/BASE_URL/|/admin/environment/config/BASE_URL/|archivebox/core/views.py"
            "Dependencies|$ADMIN_BASE_URL/admin/environment/binaries/|/admin/environment/binaries/|archivebox/config/views.py"
            "Dependency detail|$ADMIN_BASE_URL/admin/environment/binaries/abxbus/|/admin/environment/binaries/abxbus/|archivebox/config/views.py"
            "Plugins|$ADMIN_BASE_URL/admin/environment/plugins/|/admin/environment/plugins/|archivebox/plugins/views.py"
            "Workers|$ADMIN_BASE_URL/admin/environment/workers/|/admin/environment/workers/|archivebox/config/views.py"
            "Worker detail|$ADMIN_BASE_URL/admin/environment/workers/supervisord/|/admin/environment/workers/supervisord/|archivebox/config/views.py"
            "Logs|$ADMIN_BASE_URL/admin/environment/logs/|/admin/environment/logs/|archivebox/config/views.py"
            "Log detail|$ADMIN_BASE_URL/admin/environment/logs/supervisord/|/admin/environment/logs/supervisord/|archivebox/config/views.py"
        )

    fi

    if [[ "$name" == "Snapshot View (capture in progress)" ]]; then
        if ! wait "$ARCHIVE_PID"; then
            echo "[!] Sweeting.me capture failed after the live progress screenshot" >&2
            tail -100 "$CAPTURE_ROOT/sweeting-live-capture.log" >&2
            exit 1
        fi
        ARCHIVE_PID=""
        stop_background_runner

        # Discover the selectable outputs only after the real foreground
        # capture finishes. Loading another output-heavy snapshot page while
        # its extractors are running can starve navigation on the same server.
        SNAPSHOT_DISCOVERY_REPORT="$CAPTURE_ROOT/snapshot-output-discovery.json"
        NODE_PATH="$ABXPKG_LIB_DIR/pnpm/packages/chrome/node_modules" \
            CHROME_BINARY="$SCREENSHOT_CHROME_BINARY" \
            SCREENSHOT_USER_DATA_DIR="$PERSONAS_DIR/$ACTIVE_PERSONA/chrome_profile" \
            SCREENSHOT_SNAPSHOT_HEADER=expanded \
            SCREENSHOT_WIDTH=1600 \
            SCREENSHOT_HEIGHT=1000 \
            node "$REPO_DIR/bin/take_screenshot.js" "$LIVE_SNAPSHOT_VIEW_URL" "$CAPTURE_ROOT/snapshot-output-discovery.png" >"$SNAPSHOT_DISCOVERY_REPORT"
        SNAPSHOT_OUTPUT_PLUGINS="$(UI_SCREENSHOT_DISCOVERY_REPORT="$SNAPSHOT_DISCOVERY_REPORT" uv run --no-cache --project "$REPO_DIR" python -c \
            'import json, os; from urllib.parse import urlsplit; report=json.load(open(os.environ["UI_SCREENSHOT_DISCOVERY_REPORT"])); print("\n".join("{}\t{}".format(output["plugin"], "wait-replay:Nick Sweeting" if urlsplit(output["previewUrl"]).path.endswith(".wacz") else "") for output in report["checks"]["snapshotOutputs"]))')"
        if [[ -z "$SNAPSHOT_OUTPUT_PLUGINS" ]]; then
            echo "[!] The Sweeting.me snapshot detail page exposed no selectable outputs" >&2
            exit 1
        fi
        while IFS=$'\t' read -r plugin_name output_capture_mode; do
            [[ -z "$plugin_name" ]] && continue
            VIEWS+=("Snapshot View ($plugin_name)|$LIVE_SNAPSHOT_VIEW_URL#$plugin_name|/|archivebox/templates/core/snapshot.html|$output_capture_mode")
        done <<<"$SNAPSHOT_OUTPUT_PLUGINS"
        VIEWS+=("Snapshot View (header collapsed)|$LIVE_SNAPSHOT_VIEW_URL|/|archivebox/templates/core/snapshot.html|snapshot-collapsed")
    fi
    if [[ "$MAX_VIEWS" != "0" && "$capture_index" -ge "$MAX_VIEWS" ]]; then
        break
    fi
done

[[ "$MAX_VIEWS" != "0" ]] && export UI_SCREENSHOT_ALLOW_PARTIAL=1
uv run --no-cache --project "$REPO_DIR" "$REPO_DIR/bin/generate_ui_screenshot_gallery.py" build \
    "$MANIFEST_FILE" "$REPO_DIR/docs/Screenshots.md" "$PUBLIC_OUTPUT_DIR/index.html"

echo "[+] Captured $capture_index views at desktop, tablet, and mobile sizes"
echo "[+] Documentation gallery: $REPO_DIR/docs/Screenshots.md"
echo "[+] GitHub Pages gallery: $PUBLIC_OUTPUT_DIR/index.html"
