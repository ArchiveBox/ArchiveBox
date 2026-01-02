#!/bin/bash
# Run ArchiveBox plugin tests with coverage
#
# All plugin tests use pytest and are located in pluginname/tests/test_*.py
#
# Usage: ./bin/test_plugins.sh [plugin_name] [--no-coverage]
#
# Examples:
#   ./bin/test_plugins.sh                     # Run all plugin tests with coverage
#   ./bin/test_plugins.sh chrome              # Run chrome plugin tests with coverage
#   ./bin/test_plugins.sh parse_*             # Run all parse_* plugin tests with coverage
#   ./bin/test_plugins.sh --no-coverage       # Run all tests without coverage
#
# Coverage results are saved to .coverage and can be viewed with:
#   coverage combine
#   coverage report
#   coverage json

set -e

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Save root directory first
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Parse arguments
PLUGIN_FILTER=""
ENABLE_COVERAGE=true

for arg in "$@"; do
    if [ "$arg" = "--no-coverage" ]; then
        ENABLE_COVERAGE=false
    else
        PLUGIN_FILTER="$arg"
    fi
done

# Reset coverage data if collecting coverage
if [ "$ENABLE_COVERAGE" = true ]; then
    echo "Resetting coverage data..."
    cd "$ROOT_DIR" || exit 1
    coverage erase
    rm -rf "$ROOT_DIR/coverage/js" 2>/dev/null
    mkdir -p "$ROOT_DIR/coverage/js"

    # Enable Python subprocess coverage
    export COVERAGE_PROCESS_START="$ROOT_DIR/pyproject.toml"
    export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"  # For sitecustomize.py

    # Enable Node.js V8 coverage (built-in, no packages needed)
    export NODE_V8_COVERAGE="$ROOT_DIR/coverage/js"

    echo "Python coverage: enabled (subprocess support)"
    echo "JavaScript coverage: enabled (NODE_V8_COVERAGE)"
    echo ""
fi

# Change to plugins directory
cd "$ROOT_DIR/archivebox/plugins" || exit 1

echo "=========================================="
echo "ArchiveBox Plugin Tests"
echo "=========================================="
echo ""

if [ -n "$PLUGIN_FILTER" ]; then
    echo "Filter: $PLUGIN_FILTER"
else
    echo "Running all plugin tests"
fi

if [ "$ENABLE_COVERAGE" = true ]; then
    echo "Coverage: enabled"
else
    echo "Coverage: disabled"
fi
echo ""

# Track results
TOTAL_PLUGINS=0
PASSED_PLUGINS=0
FAILED_PLUGINS=0

# Find and run plugin tests
if [ -n "$PLUGIN_FILTER" ]; then
    # Run tests for specific plugin(s) matching pattern
    TEST_DIRS=$(find . -maxdepth 2 -type d -path "./${PLUGIN_FILTER}*/tests" 2>/dev/null | sort)
else
    # Run all plugin tests
    TEST_DIRS=$(find . -maxdepth 2 -type d -name "tests" -path "./*/tests" 2>/dev/null | sort)
fi

if [ -z "$TEST_DIRS" ]; then
    echo -e "${YELLOW}No plugin tests found${NC}"
    [ -n "$PLUGIN_FILTER" ] && echo "Pattern: $PLUGIN_FILTER"
    exit 0
fi

for test_dir in $TEST_DIRS; do
    # Check if there are any Python test files
    if ! compgen -G "${test_dir}/test_*.py" > /dev/null 2>&1; then
        continue
    fi

    plugin_name=$(basename $(dirname "$test_dir"))
    TOTAL_PLUGINS=$((TOTAL_PLUGINS + 1))

    echo -e "${YELLOW}[RUNNING]${NC} $plugin_name"

    # Build pytest command with optional coverage
    PYTEST_CMD="python -m pytest $test_dir -p no:django -v --tb=short"
    if [ "$ENABLE_COVERAGE" = true ]; then
        PYTEST_CMD="$PYTEST_CMD --cov=$plugin_name --cov-append --cov-branch"
    fi

    if eval "$PYTEST_CMD" 2>&1 | grep -v "^platform\|^cachedir\|^rootdir\|^configfile\|^plugins:" | tail -100; then
        echo -e "${GREEN}[PASSED]${NC} $plugin_name"
        PASSED_PLUGINS=$((PASSED_PLUGINS + 1))
    else
        echo -e "${RED}[FAILED]${NC} $plugin_name"
        FAILED_PLUGINS=$((FAILED_PLUGINS + 1))
    fi
    echo ""
done

# Print summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "Total plugins tested: $TOTAL_PLUGINS"
echo -e "${GREEN}Passed:${NC}              $PASSED_PLUGINS"
echo -e "${RED}Failed:${NC}              $FAILED_PLUGINS"
echo ""

if [ $TOTAL_PLUGINS -eq 0 ]; then
    echo -e "${YELLOW}⚠ No tests found${NC}"
    exit 0
elif [ $FAILED_PLUGINS -eq 0 ]; then
    echo -e "${GREEN}✓ All plugin tests passed!${NC}"

    # Show coverage summary if enabled
    if [ "$ENABLE_COVERAGE" = true ]; then
        echo ""
        echo "=========================================="
        echo "Python Coverage Summary"
        echo "=========================================="
        # Coverage data is in ROOT_DIR, combine and report from there
        cd "$ROOT_DIR" || exit 1
        # Copy coverage data from plugins dir if it exists
        if [ -f "$ROOT_DIR/archivebox/plugins/.coverage" ]; then
            cp "$ROOT_DIR/archivebox/plugins/.coverage" "$ROOT_DIR/.coverage"
        fi
        coverage combine 2>/dev/null || true
        coverage report --include="archivebox/plugins/*" --omit="*/tests/*" 2>&1 | head -50
        echo ""

        echo "=========================================="
        echo "JavaScript Coverage Summary"
        echo "=========================================="
        if [ -d "$ROOT_DIR/coverage/js" ] && [ "$(ls -A "$ROOT_DIR/coverage/js" 2>/dev/null)" ]; then
            node "$ROOT_DIR/bin/convert_v8_coverage.js" "$ROOT_DIR/coverage/js"
        else
            echo "No JavaScript coverage data collected"
            echo "(JS hooks may not have been executed during tests)"
        fi
        echo ""

        echo "For detailed coverage reports (from project root):"
        echo "  Python:     coverage report --show-missing --include='archivebox/plugins/*' --omit='*/tests/*'"
        echo "  Python:     coverage json  # LLM-friendly format"
        echo "  Python:     coverage html  # Interactive HTML report"
        echo "  JavaScript: node bin/convert_v8_coverage.js coverage/js"
    fi

    exit 0
else
    echo -e "${RED}✗ Some plugin tests failed${NC}"
    exit 1
fi
