#!/bin/bash
# Run ArchiveBox plugin tests with coverage
#
# All plugin tests use pytest and are located in pluginname/tests/test_*.py
#
# Usage: ./bin/test_plugins.sh [plugin_name] [--no-coverage] [--coverage-report]
#
# Examples:
#   ./bin/test_plugins.sh                     # Run all plugin tests with coverage
#   ./bin/test_plugins.sh chrome              # Run chrome plugin tests with coverage
#   ./bin/test_plugins.sh parse_*             # Run all parse_* plugin tests with coverage
#   ./bin/test_plugins.sh --no-coverage       # Run all tests without coverage
#   ./bin/test_plugins.sh --coverage-report   # Just show coverage report without running tests
#
# For running individual hooks with coverage:
#   NODE_V8_COVERAGE=./coverage/js node <hook>.js [args]  # JS hooks
#   coverage run --parallel-mode <hook>.py [args]         # Python hooks
#
# Coverage results are saved to .coverage (Python) and coverage/js (JavaScript):
#   coverage combine && coverage report
#   coverage json
#   ./bin/test_plugins.sh --coverage-report

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
COVERAGE_REPORT_ONLY=false

for arg in "$@"; do
    if [ "$arg" = "--no-coverage" ]; then
        ENABLE_COVERAGE=false
    elif [ "$arg" = "--coverage-report" ]; then
        COVERAGE_REPORT_ONLY=true
    else
        PLUGIN_FILTER="$arg"
    fi
done

# Function to show JS coverage report (inlined from convert_v8_coverage.js)
show_js_coverage() {
    local coverage_dir="$1"

    if [ ! -d "$coverage_dir" ] || [ -z "$(ls -A "$coverage_dir" 2>/dev/null)" ]; then
        echo "No JavaScript coverage data collected"
        echo "(JS hooks may not have been executed during tests)"
        return
    fi

    node - "$coverage_dir" << 'ENDJS'
const fs = require('fs');
const path = require('path');
const coverageDir = process.argv[2];

const files = fs.readdirSync(coverageDir).filter(f => f.startsWith('coverage-') && f.endsWith('.json'));
if (files.length === 0) {
    console.log('No coverage files found');
    process.exit(0);
}

const coverageByFile = {};

files.forEach(file => {
    const data = JSON.parse(fs.readFileSync(path.join(coverageDir, file), 'utf8'));
    data.result.forEach(script => {
        const url = script.url;
        if (url.startsWith('node:') || url.includes('node_modules')) return;

        if (!coverageByFile[url]) {
            coverageByFile[url] = { totalRanges: 0, executedRanges: 0 };
        }

        script.functions.forEach(func => {
            func.ranges.forEach(range => {
                coverageByFile[url].totalRanges++;
                if (range.count > 0) coverageByFile[url].executedRanges++;
            });
        });
    });
});

const allFiles = Object.keys(coverageByFile).sort();
const pluginFiles = allFiles.filter(url => url.includes('archivebox/plugins'));
const otherFiles = allFiles.filter(url => !url.startsWith('node:') && !url.includes('archivebox/plugins'));

console.log('Total files with coverage: ' + allFiles.length + '\n');
console.log('Plugin files: ' + pluginFiles.length);
console.log('Node internal: ' + allFiles.filter(u => u.startsWith('node:')).length);
console.log('Other: ' + otherFiles.length + '\n');

console.log('JavaScript Coverage Report');
console.log('='.repeat(80));
console.log('');

if (otherFiles.length > 0) {
    console.log('Non-plugin files with coverage:');
    otherFiles.forEach(url => console.log('  ' + url));
    console.log('');
}

if (pluginFiles.length === 0) {
    console.log('No plugin files covered');
    process.exit(0);
}

let totalRanges = 0, totalExecuted = 0;

pluginFiles.forEach(url => {
    const cov = coverageByFile[url];
    const pct = cov.totalRanges > 0 ? (cov.executedRanges / cov.totalRanges * 100).toFixed(1) : '0.0';
    const match = url.match(/archivebox\/plugins\/.+/);
    const displayPath = match ? match[0] : url;
    console.log(displayPath + ': ' + pct + '% (' + cov.executedRanges + '/' + cov.totalRanges + ' ranges)');
    totalRanges += cov.totalRanges;
    totalExecuted += cov.executedRanges;
});

console.log('');
console.log('-'.repeat(80));
const overallPct = totalRanges > 0 ? (totalExecuted / totalRanges * 100).toFixed(1) : '0.0';
console.log('Total: ' + overallPct + '% (' + totalExecuted + '/' + totalRanges + ' ranges)');
ENDJS
}

# If --coverage-report only, just show the report and exit
if [ "$COVERAGE_REPORT_ONLY" = true ]; then
    cd "$ROOT_DIR" || exit 1
    echo "=========================================="
    echo "Python Coverage Summary"
    echo "=========================================="
    coverage combine 2>/dev/null || true
    coverage report --include="archivebox/plugins/*" --omit="*/tests/*"
    echo ""

    echo "=========================================="
    echo "JavaScript Coverage Summary"
    echo "=========================================="
    show_js_coverage "$ROOT_DIR/coverage/js"
    echo ""

    echo "For detailed coverage reports:"
    echo "  Python:     coverage report --show-missing --include='archivebox/plugins/*' --omit='*/tests/*'"
    echo "  Python:     coverage json  # LLM-friendly format"
    echo "  Python:     coverage html  # Interactive HTML report"
    exit 0
fi

# Set DATA_DIR for tests (required by abx_pkg and plugins)
# Use temp dir to isolate tests from project files
if [ -z "$DATA_DIR" ]; then
    export DATA_DIR=$(mktemp -d -t archivebox_plugin_tests.XXXXXX)
    # Clean up on exit
    trap "rm -rf '$DATA_DIR'" EXIT
fi

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
        show_js_coverage "$ROOT_DIR/coverage/js"
        echo ""

        echo "For detailed coverage reports (from project root):"
        echo "  Python:     coverage report --show-missing --include='archivebox/plugins/*' --omit='*/tests/*'"
        echo "  Python:     coverage json  # LLM-friendly format"
        echo "  Python:     coverage html  # Interactive HTML report"
        echo "  JavaScript: ./bin/test_plugins.sh --coverage-report"
    fi

    exit 0
else
    echo -e "${RED}✗ Some plugin tests failed${NC}"
    exit 1
fi
