#!/bin/bash
# Run ArchiveBox plugin tests
#
# All plugin tests use pytest and are located in pluginname/tests/test_*.py
#
# Usage: ./bin/run_plugin_tests.sh [plugin_name]
#
# Examples:
#   ./bin/run_plugin_tests.sh                 # Run all plugin tests
#   ./bin/run_plugin_tests.sh chrome          # Run chrome plugin tests
#   ./bin/run_plugin_tests.sh parse_*         # Run all parse_* plugin tests

set -e

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
PLUGIN_FILTER="${1:-}"

# Change to plugins directory
cd "$(dirname "$0")/../archivebox/plugins" || exit 1

echo "=========================================="
echo "ArchiveBox Plugin Tests"
echo "=========================================="
echo ""

if [ -n "$PLUGIN_FILTER" ]; then
    echo "Filter: $PLUGIN_FILTER"
else
    echo "Running all plugin tests"
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

    if python -m pytest "$test_dir" -p no:django -v --tb=short 2>&1 | grep -v "^platform\|^cachedir\|^rootdir\|^configfile\|^plugins:" | tail -100; then
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
    exit 0
else
    echo -e "${RED}✗ Some plugin tests failed${NC}"
    exit 1
fi
