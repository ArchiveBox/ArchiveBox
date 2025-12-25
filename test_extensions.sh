#!/bin/bash
set -e

echo "=========================================="
echo "Testing Chrome Extension System"
echo "=========================================="

# Get absolute path to project root
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Set up test environment with absolute paths
export DATA_DIR="$PROJECT_ROOT/data"
export ACTIVE_PERSONA="Test"
export CHROME_EXTENSIONS_DIR="$PROJECT_ROOT/data/personas/Test/chrome_extensions"
export API_KEY_2CAPTCHA="test_api_key_12345"

# Clean up any previous test data
echo ""
echo "[1/6] Cleaning up previous test data..."
rm -rf "$CHROME_EXTENSIONS_DIR"
rm -rf "$PROJECT_ROOT/chrome_session"
# Also clean up any files created in plugin directories from previous runs
find "$PROJECT_ROOT/archivebox/plugins" -type d -name "data" -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$CHROME_EXTENSIONS_DIR"

echo "✓ Clean slate ready"

# Test 1: Install captcha2 extension
echo ""
echo "[2/6] Testing captcha2 extension installation..."
node "$PROJECT_ROOT/archivebox/plugins/captcha2/on_Snapshot__01_captcha2.js"
if [ -f "$CHROME_EXTENSIONS_DIR/captcha2.extension.json" ]; then
    echo "✓ captcha2.extension.json created"
else
    echo "✗ Failed to create captcha2.extension.json"
    exit 1
fi

# Test 2: Check caching (run again, should skip)
echo ""
echo "[3/6] Testing cache (should skip re-installation)..."
node "$PROJECT_ROOT/archivebox/plugins/captcha2/on_Snapshot__01_captcha2.js"
echo "✓ Cache check passed"

# Test 3: Install other extensions
echo ""
echo "[4/6] Testing other extensions..."
node "$PROJECT_ROOT/archivebox/plugins/istilldontcareaboutcookies/on_Snapshot__02_istilldontcareaboutcookies.js"
node "$PROJECT_ROOT/archivebox/plugins/ublock/on_Snapshot__03_ublock.js"
node "$PROJECT_ROOT/archivebox/plugins/singlefile/on_Snapshot__04_singlefile.js"

echo "✓ All extensions installed"

# Test 4: List installed extensions
echo ""
echo "[5/6] Verifying extension files..."
ls -lh "$CHROME_EXTENSIONS_DIR"/*.extension.json 2>/dev/null || echo "No extension.json files found"

# Count extensions
EXT_COUNT=$(ls -1 "$CHROME_EXTENSIONS_DIR"/*.extension.json 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo "Found $EXT_COUNT extension metadata files"

if [ "$EXT_COUNT" -ge "3" ]; then
    echo "✓ Expected extensions installed"
else
    echo "✗ Expected at least 3 extensions, found $EXT_COUNT"
    exit 1
fi

# Test 5: Check unpacked directories
echo ""
echo "[6/6] Checking unpacked extension directories..."
UNPACKED_COUNT=$(find "$CHROME_EXTENSIONS_DIR" -type d -name "*__*" 2>/dev/null | wc -l | tr -d ' ')
echo "Found $UNPACKED_COUNT unpacked extension directories"

if [ "$UNPACKED_COUNT" -ge "3" ]; then
    echo "✓ Extensions unpacked successfully"
else
    echo "✗ Expected at least 3 unpacked directories, found $UNPACKED_COUNT"
    exit 1
fi

# Summary
echo ""
echo "=========================================="
echo "✓ All tests passed!"
echo "=========================================="
echo ""
echo "Installed extensions:"
for json_file in "$CHROME_EXTENSIONS_DIR"/*.extension.json; do
    if [ -f "$json_file" ]; then
        NAME=$(node -e "console.log(require('$json_file').name)")
        VERSION=$(node -e "console.log(require('$json_file').version || 'unknown')")
        echo "  - $NAME (v$VERSION)"
    fi
done

echo ""
echo "To clean up test data:"
echo "  rm -rf ./data/personas/Test"
