#!/bin/bash
# Run all plugin tests
#
# Usage: ./run_all_tests.sh

set -e

echo "=========================================="
echo "Running All Plugin Tests"
echo "=========================================="
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track results
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

run_test_suite() {
    local test_file=$1
    local test_name=$(basename $(dirname $test_file))

    echo -e "${YELLOW}[RUNNING]${NC} $test_name tests..."

    if node --test "$test_file" 2>&1; then
        echo -e "${GREEN}[PASSED]${NC} $test_name tests"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}[FAILED]${NC} $test_name tests"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo ""
}

# Find and run all test files
echo "Finding test files..."
echo ""

# Chrome extensions utils tests
if [ -f "chrome_extensions/tests/test_chrome_extension_utils.js" ]; then
    run_test_suite "chrome_extensions/tests/test_chrome_extension_utils.js"
fi

# Captcha2 tests
if [ -f "captcha2/tests/test_captcha2_install.js" ]; then
    run_test_suite "captcha2/tests/test_captcha2_install.js"
fi

if [ -f "captcha2/tests/test_captcha2_config.js" ]; then
    run_test_suite "captcha2/tests/test_captcha2_config.js"
fi

# I Still Don't Care About Cookies tests
if [ -f "istilldontcareaboutcookies/tests/test_istilldontcareaboutcookies.js" ]; then
    run_test_suite "istilldontcareaboutcookies/tests/test_istilldontcareaboutcookies.js"
fi

# uBlock tests
if [ -f "ublock/tests/test_ublock.js" ]; then
    run_test_suite "ublock/tests/test_ublock.js"
fi

# SingleFile tests
if [ -f "singlefile/tests/test_singlefile.js" ]; then
    run_test_suite "singlefile/tests/test_singlefile.js"
fi

# Print summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "Total test suites:  $TOTAL_TESTS"
echo -e "${GREEN}Passed:${NC}            $PASSED_TESTS"
echo -e "${RED}Failed:${NC}            $FAILED_TESTS"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
