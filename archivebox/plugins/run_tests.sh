#!/bin/bash
# Run all plugin tests
#
# Usage: ./run_tests.sh [plugin_name]
#
# Examples:
#   ./run_tests.sh                 # Run all tests
#   ./run_tests.sh captcha2        # Run only captcha2 tests
#   ./run_tests.sh chrome_*        # Run all chrome tests

set -e

echo "=========================================="
echo "Running ArchiveBox Plugin Tests"
echo "=========================================="
echo ""

if [ -n "$1" ]; then
    echo "Running tests for: $1"
    python -m pytest "$1"/tests/ -v
else
    echo "Running all plugin tests..."
    python -m pytest */tests/test_*.py -v
fi

echo ""
echo "=========================================="
echo "Tests Complete"
echo "=========================================="
