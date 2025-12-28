#!/usr/bin/env bash
# Kill zombie Chrome/Chromium processes listening on 127.0.0.1
# Works cross-platform on macOS and Linux
#
# Usage:
#   ./bin/kill_chrome.sh           # Kill Chrome processes with verification
#   ./bin/kill_chrome.sh --pkill   # Quick kill using pkill (less precise)
#   ./bin/kill_chrome.sh --help    # Show this help

set -e

# Detect OS
OS="$(uname -s)"

# Chrome binary patterns to search for (cross-platform)
CHROME_PATTERNS=(
    "Google Chrome"
    "google-chrome"
    "chrome"
    "chromium"
    "chromium-browser"
    "Chromium"
)

# Function to kill Chrome processes
kill_chrome_processes() {
    echo "Searching for Chrome processes listening on 127.0.0.1..."
    local killed=0

    for pattern in "${CHROME_PATTERNS[@]}"; do
        # Find processes matching the pattern with remote debugging
        if [ "$OS" = "Darwin" ]; then
            # macOS
            pids=$(ps aux | grep -i "$pattern" | grep -E "(remote-debugging-port|remote-debugging-address=127\.0\.0\.1)" | grep -v grep | awk '{print $2}' || true)
        else
            # Linux
            pids=$(ps aux | grep -i "$pattern" | grep -E "(remote-debugging-port|remote-debugging-address=127\.0\.0\.1)" | grep -v grep | awk '{print $2}' || true)
        fi

        if [ -n "$pids" ]; then
            echo "Found Chrome processes ($pattern): $pids"
            for pid in $pids; do
                # Try regular kill first
                if kill "$pid" 2>/dev/null; then
                    echo "  Killed $pid"
                    killed=$((killed + 1))
                    sleep 0.1
                fi

                # Check if still alive
                if ps -p "$pid" > /dev/null 2>&1; then
                    # Check process state first to avoid attempting impossible kills
                    if [ "$OS" = "Darwin" ]; then
                        state=$(ps -o state -p "$pid" 2>/dev/null | tail -1 | tr -d ' ')
                    else
                        state=$(ps -o stat -p "$pid" 2>/dev/null | tail -1 | tr -d ' ')
                    fi

                    # Check if it's a zombie/uninterruptible process BEFORE trying to kill
                    if [[ "$state" == *"Z"* ]] || [[ "$state" == *"D"* ]] || [[ "$state" == *"UNE"* ]]; then
                        echo "  WARNING: $pid is in uninterruptible/zombie state ($state) - cannot be killed"
                        echo "           Process will clean up automatically or requires system reboot"
                    else
                        # Try force kill
                        echo "  Force killing $pid with -9..."
                        if kill -9 "$pid" 2>/dev/null; then
                            # Wait briefly and verify
                            sleep 0.2
                            if ! ps -p "$pid" > /dev/null 2>&1; then
                                echo "  Force killed $pid"
                                killed=$((killed + 1))
                            else
                                echo "  WARNING: $pid survived kill -9 (state: $state)"
                            fi
                        else
                            echo "  ERROR: Failed to kill $pid (state: $state)"
                        fi
                    fi
                fi
            done
        fi
    done

    if [ $killed -eq 0 ]; then
        echo "No Chrome processes listening on 127.0.0.1 found (or all are zombie/uninterruptible)"
    else
        echo "Successfully killed $killed Chrome process(es)"
    fi

    # Show remaining Chrome processes (if any)
    echo ""
    echo "Remaining Chrome processes listening on 127.0.0.1:"
    for pattern in "${CHROME_PATTERNS[@]}"; do
        ps aux | grep -i "$pattern" | grep -E "(remote-debugging-port|remote-debugging-address=127\.0\.0\.1)" | grep -v grep || true
    done | head -10

    if [ $(ps aux | grep -iE "(google chrome|chrome|chromium)" | grep -E "(remote-debugging-port|remote-debugging-address=127\.0\.0\.1)" | grep -v grep | wc -l) -eq 0 ]; then
        echo "  (none)"
    fi
}

# Alternative approach using pkill (faster but less precise)
kill_chrome_pkill() {
    echo "Using pkill to kill all Chrome processes..."

    for pattern in "${CHROME_PATTERNS[@]}"; do
        if pkill -9 -f "$pattern" 2>/dev/null; then
            echo "  Killed processes matching: $pattern"
        fi
    done

    sleep 0.5
    echo "Done"
}

# Show help
show_help() {
    cat << EOF
Kill zombie Chrome/Chromium processes listening on 127.0.0.1

Usage:
  $0 [OPTIONS]

Options:
  (none)           Kill Chrome processes with state verification (recommended)
  --pkill, -p      Quick kill using pkill (faster but less precise)
  --help, -h       Show this help message

Description:
  This script finds and kills Chrome/Chromium processes that are listening
  on 127.0.0.1 (with --remote-debugging-port or --remote-debugging-address).

  Supports multiple Chrome binary names:
    - Google Chrome / chrome / google-chrome
    - Chromium / chromium / chromium-browser

  Works on macOS and Linux.

  Zombie/uninterruptible processes (state UNE/Z/D) will be detected and
  reported but cannot be killed. They will clean up automatically.

Examples:
  $0                 # Kill with verification
  $0 --pkill         # Quick kill all Chrome processes

EOF
}

# Parse arguments
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_help
elif [ "$1" = "--pkill" ] || [ "$1" = "-p" ]; then
    kill_chrome_pkill
else
    kill_chrome_processes
fi
