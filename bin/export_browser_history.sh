#!/bin/bash

OUTPUT_DIR="$(pwd)"

if [[ "$1" == "--chrome" ]]; then
    # Google Chrome / Chromium
    if [[ -e "$2" ]]; then
        cp "$2" "$OUTPUT_DIR/chrome_history.db.tmp"
    else
        default=$(ls ~/Library/Application\ Support/Google/Chrome/Default/History)
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        cp "$default" "$OUTPUT_DIR/chrome_history.db.tmp"
    fi

    sqlite3 "$OUTPUT_DIR/chrome_history.db.tmp" "SELECT \"[\" || group_concat(json_object('timestamp', last_visit_time, 'description', title, 'href', url)) || \"]\" FROM urls;" > "$OUTPUT_DIR/chrome_history.json"
    jq < "$(dirname "${2:-$default}")"/Bookmarks '.roots.other.children[] | {href: .url, description: .name, timestamp: .date_added}' > "$OUTPUT_DIR/chrome_bookmarks.json"
    
    rm "$DATA_DIR"/output/sources/chrome_history.db.*
    echo "Chrome history exported to:"
    echo "    output/sources/chrome_history.json"
fi

if [[ "$1" == "--firefox" ]]; then
    # Firefox
    if [[ -e "$2" ]]; then
        cp "$2" "$OUTPUT_DIR/firefox_history.db.tmp"
    else
        default=$(ls ~/Library/Application\ Support/Firefox/Profiles/*.default/places.sqlite)
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        cp "$default" "$OUTPUT_DIR/firefox_history.db.tmp"
    fi
    
    sqlite3 "$OUTPUT_DIR/firefox_history.db.tmp" "SELECT \"[\" || group_concat(json_object('timestamp', last_visit_date, 'description', title, 'href', url)) || \"]\" FROM moz_places;" > "$OUTPUT_DIR/firefox_history.json"
    sqlite3 "$OUTPUT_DIR/firefox_history.db.tmp" "SELECT \"[\" || group_concat(json_object('timestamp', b.dateAdded, 'description', b.title, 'href', f.url)) || \"]\" FROM moz_bookmarks AS b JOIN moz_places AS f ON f.id = b.fk" > "$OUTPUT_DIR/firefox_bookmarks.json"
    
    rm "$DATA_DIR"/output/sources/firefox_history.db.*
    echo "Firefox history exported to:"
    echo "    output/sources/firefox_history.json"
    echo "    output/sources/firefox_bookmarks.json"
fi

if [[ "$1" == "--safari" ]]; then
    # Safari
    if [[ -e "$2" ]]; then
        cp "$2" "$OUTPUT_DIR/safari_history.db.tmp"
    else
        default="~/Library/Safari/History.db"
        echo "Defaulting to history db: $default"
        echo "Optionally specify the path to a different sqlite history database as the 2nd argument."
        cp "$default" "$OUTPUT_DIR/safari_history.db.tmp"
    fi
    
    sqlite3 "$OUTPUT_DIR/safari_history.db.tmp" "select url from history_items" > "$OUTPUT_DIR/safari_history.json"
    
    rm "$DATA_DIR"/output/sources/safari_history.db.*
    echo "Safari history exported to:"
    echo "    output/sources/safari_history.json"
fi
