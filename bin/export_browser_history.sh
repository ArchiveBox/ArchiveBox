#!/usr/bin/env bash
#
# Helper script to export browser history and bookmarks to a format ArchiveBox can ingest.
# Usage:
#    curl -O 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/export_browser_history.sh'
#    bash export_browser_history.sh --chrome
#    bash export_browser_history.sh --firefox
#    bash export_browser_history.sh --safari
#    ls
#        chrome_history.json
#        chrome_bookmarks.json
#        firefox_history.json
#        firefox_bookmarks.json
#        safari_history.json
#
# Assumptions:
#
# * you're running this on macOS or Linux
# * you're running a reasonably modern version of Bash
#   * macOS users: `brew install bash`
#
# Dependencies:
#
# * abxpkg (Python, sqlite3, and jq are resolved through it)
# * jq (for chrome bookmarks)
#

set -Eeuo pipefail

BROWSER_TO_EXPORT="${1?Please specify --chrome, --firefox, or --safari}"
OUTPUT_DIR="$(pwd)"
: "${ABXPKG_LIB_DIR:?Set ABXPKG_LIB_DIR to the ArchiveBox package library directory}"

for binary in python sqlite3 jq; do
    abxpkg install "$binary" --lib "$ABXPKG_LIB_DIR" --binproviders env,brew,apt
done

PYTHON_BINARY="$ABXPKG_LIB_DIR/env/bin/python"
SQLITE3_BINARY="$ABXPKG_LIB_DIR/env/bin/sqlite3"
JQ_BINARY="$ABXPKG_LIB_DIR/env/bin/jq"
for binary_path in "$PYTHON_BINARY" "$SQLITE3_BINARY" "$JQ_BINARY"; do
    test -L "$binary_path"
    test -x "$binary_path"
done

is_linux() {
    [[ "$OSTYPE" == linux* ]]
}

find_firefox_places_db() {
    local candidates=()
    shopt -s nullglob
    if is_linux; then
        candidates=(~/.mozilla/firefox/*.default*/places.sqlite)
    else
        candidates=(~/Library/Application\ Support/Firefox/Profiles/*.default*/places.sqlite)
    fi
    shopt -u nullglob
    [[ ${#candidates[@]} -gt 0 ]] || return 1
    printf '%s\n' "${candidates[0]}"
}

find_chrome_history_db() {
    if is_linux; then
        local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
        for path in \
            "${config_home}/chromium/Default/History" \
            "${config_home}/google-chrome/Default/History";
        do
            if [ -f "${path}" ]; then
                echo "${path}"
                return
            fi
        done

        echo "Unable to find Chrome history database. You can supply it manually as a second parameter." >&2
        exit 1
    else
        echo ~/Library/Application\ Support/Google/Chrome/Default/History
    fi
}

export_chrome() {
    local history_db="${2:-}"
    if [[ -e "$history_db" ]]; then
        if [[ "$history_db" != /* ]]; then
            history_db="$(pwd)/$history_db"
        fi
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$history_db" "$OUTPUT_DIR/chrome_history.db.tmp"
    else
        history_db="$(find_chrome_history_db)"
        if [[ "$history_db" != /* ]]; then
            history_db="$(pwd)/$history_db"
        fi
        default="$history_db"
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$default" "$OUTPUT_DIR/chrome_history.db.tmp"
    fi

    "$SQLITE3_BINARY" "$OUTPUT_DIR/chrome_history.db.tmp" "
    SELECT '[' || group_concat(
        json_object('timestamp', last_visit_time, 'description', title, 'href', url)
    ) || ']'
    FROM urls;" > "$OUTPUT_DIR/chrome_history.json"

    "$JQ_BINARY" '[.roots[]?.children[]? | select(.url) | {href: .url, description: .name, timestamp: .date_added}]' \
       < "${history_db%/*}/Bookmarks" \
       > "$OUTPUT_DIR/chrome_bookmarks.json"

    "$PYTHON_BINARY" -c 'import pathlib, sys; [pathlib.Path(path).unlink() for path in sys.argv[1:]]' \
        "$OUTPUT_DIR"/chrome_history.db.*
    echo "Chrome history exported to:"
    echo "    $OUTPUT_DIR/chrome_history.json"
    echo "    $OUTPUT_DIR/chrome_bookmarks.json"
}

export_firefox() {
    if [[ -e "${2:-}" ]]; then
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$2" "$OUTPUT_DIR/firefox_history.db.tmp"
    else
        default="$(find_firefox_places_db)"
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$default" "$OUTPUT_DIR/firefox_history.db.tmp"
    fi

    "$SQLITE3_BINARY" "$OUTPUT_DIR/firefox_history.db.tmp" "
    SELECT
        '[' || group_concat(
            json_object(
                'timestamp', last_visit_date,
                'description', title,
                'href', url
            )
        ) || ']'
    FROM moz_places;" > "$OUTPUT_DIR/firefox_history.json"

    "$SQLITE3_BINARY" "$OUTPUT_DIR/firefox_history.db.tmp" "
    with recursive tags AS (
          select id, title, '' AS tags
          FROM moz_bookmarks
          where parent == 0
        UNION ALL
          select c.id, p.title, c.title || ',' || tags AS tags
          from moz_bookmarks AS c
          JOIN tags AS p
          ON c.parent = p.id
        )

        SELECT '[' || group_concat(json_object('timestamp', b.dateAdded, 'description', b.title, 'href', f.url, 'tags', tags.tags)) || ']'
        FROM moz_bookmarks AS b
        JOIN moz_places AS f ON f.id = b.fk
        JOIN tags ON tags.id = b.parent
        WHERE f.url LIKE '%://%';" > "$OUTPUT_DIR/firefox_bookmarks.json"

    "$PYTHON_BINARY" -c 'import pathlib, sys; [pathlib.Path(path).unlink() for path in sys.argv[1:]]' \
        "$OUTPUT_DIR"/firefox_history.db.*
    echo "Firefox history exported to:"
    echo "    $OUTPUT_DIR/firefox_history.json"
    echo "    $OUTPUT_DIR/firefox_bookmarks.json"
}

export_safari() {
    if [[ -e "${2:-}" ]]; then
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$2" "$OUTPUT_DIR/safari_history.db.tmp"
    else
        default="$HOME/Library/Safari/History.db"
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        "$PYTHON_BINARY" -c 'import shutil, sys; shutil.copy2(sys.argv[1], sys.argv[2])' \
            "$default" "$OUTPUT_DIR/safari_history.db.tmp"
    fi

    "$SQLITE3_BINARY" "$OUTPUT_DIR/safari_history.db.tmp" "select url from history_items" > "$OUTPUT_DIR/safari_history.json"

    "$PYTHON_BINARY" -c 'import pathlib, sys; [pathlib.Path(path).unlink() for path in sys.argv[1:]]' \
        "$OUTPUT_DIR"/safari_history.db.*
    echo "Safari history exported to:"
    echo "    $OUTPUT_DIR/safari_history.json"
}

if [[ "$BROWSER_TO_EXPORT" == "--chrome" ]]; then
    export_chrome "$@"
elif [[ "$BROWSER_TO_EXPORT" == "--firefox" ]]; then
    export_firefox "$@"
elif [[ "$BROWSER_TO_EXPORT" == "--safari" ]]; then
    export_safari "$@"
else
    echo "Unrecognized argument: $1" >&2
    exit 1
fi
