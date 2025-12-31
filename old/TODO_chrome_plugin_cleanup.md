# Chrome Plugin Consolidation - COMPLETED ✓

## Core Principle: One ArchiveResult Per Plugin

**Critical Realization:** Each plugin must produce exactly ONE ArchiveResult output. This is fundamental to ArchiveBox's architecture - you cannot have multiple outputs from a single plugin.

### CRITICAL ARCHITECTURE CLARIFICATION

**DO NOT CONFUSE THESE CONCEPTS:**

1. **Plugin** = Directory name (e.g., `chrome`, `consolelog`, `screenshot`)
   - Lives in `archivebox/plugins/<plugin_name>/`
   - Can contain MULTIPLE hook files
   - Produces ONE output directory: `users/{username}/snapshots/YYYYMMDD/{domain}/{snap_id}/{plugin_name}/`
   - Creates ONE ArchiveResult record per snapshot

2. **Hook** = Individual script file (e.g., `on_Snapshot__20_chrome_tab.bg.js`)
   - Lives inside a plugin directory
   - One plugin can have MANY hooks
   - All hooks in a plugin run sequentially when that plugin's ArchiveResult is processed
   - All hooks write to the SAME output directory (the plugin directory)

3. **Extractor** = ArchiveResult.extractor field = PLUGIN NAME (not hook name)
   - `ArchiveResult.extractor = 'chrome'` (plugin name)
   - NOT `ArchiveResult.extractor = '20_chrome_tab.bg'` (hook name)

4. **Output Directory** = `users/{username}/snapshots/YYYYMMDD/{domain}/{snap_id}/{plugin_name}/`
   - One output directory per plugin (0.9.x structure)
   - ALL hooks in that plugin write to this same directory
   - Example: `users/default/snapshots/20251227/example.com/019b-6397-6a5b/chrome/` contains outputs from ALL chrome hooks
   - Legacy: `archive/{timestamp}/` with symlink for backwards compatibility

**Example 1: Chrome Plugin (Infrastructure - NO ArchiveResult)**
```
Plugin name: 'chrome'
ArchiveResult: NONE (infrastructure only)
Output directory: users/default/snapshots/20251227/example.com/019b-6397-6a5b/chrome/

Hooks:
  - on_Snapshot__20_chrome_tab.bg.js       # Launches Chrome, opens tab
  - on_Snapshot__30_chrome_navigate.js     # Navigates to URL
  - on_Snapshot__45_chrome_tab_cleanup.py  # Kills Chrome on cleanup

Writes (temporary infrastructure files, deleted on cleanup):
  - chrome/cdp_url.txt          # Other plugins read this to connect
  - chrome/target_id.txt          # Tab ID for CDP connection
  - chrome/page_loaded.txt      # Navigation completion marker
  - chrome/navigation.json      # Navigation state
  - chrome/hook.pid             # For cleanup

NO ArchiveResult JSON is produced - this is pure infrastructure.
On SIGTERM: Chrome exits, chrome/ directory is deleted.
```

**Example 2: Screenshot Plugin (Output Plugin - CREATES ArchiveResult)**
```
Plugin name: 'screenshot'
ArchiveResult.extractor: 'screenshot'
Output directory: users/default/snapshots/20251227/example.com/019b-6397-6a5b/screenshot/

Hooks:
  - on_Snapshot__34_screenshot.js

Process:
  1. Reads ../chrome/cdp_url.txt to get Chrome connection
  2. Connects to Chrome CDP
  3. Takes screenshot
  4. Writes to: screenshot/screenshot.png
  5. Emits ArchiveResult JSON to stdout

Creates ArchiveResult with status=succeeded, output_files={'screenshot.png': {}}
```

**Example 3: PDF Plugin (Output Plugin - CREATES ArchiveResult)**
```
Plugin name: 'pdf'
ArchiveResult.extractor: 'pdf'
Output directory: users/default/snapshots/20251227/example.com/019b-6397-6a5b/pdf/

Hooks:
  - on_Snapshot__35_pdf.js

Process:
  1. Reads ../chrome/cdp_url.txt to get Chrome connection
  2. Connects to Chrome CDP
  3. Generates PDF
  4. Writes to: pdf/output.pdf
  5. Emits ArchiveResult JSON to stdout

Creates ArchiveResult with status=succeeded, output_files={'output.pdf': {}}
```

**Lifecycle:**
```
1. Chrome hooks run → create chrome/ dir with infrastructure files
2. Screenshot/PDF/etc hooks run → read chrome/cdp_url.txt, write to their own dirs
3. Snapshot.cleanup() called → sends SIGTERM to background hooks
4. Chrome receives SIGTERM → exits, deletes chrome/ dir
5. Screenshot/PDF/etc dirs remain with their outputs
```

**DO NOT:**
- Create one ArchiveResult per hook
- Use hook names as extractor values
- Create separate output directories per hook

**DO:**
- Create one ArchiveResult per plugin
- Use plugin directory name as extractor value
- Run all hooks in a plugin when processing its ArchiveResult
- Write all hook outputs to the same plugin directory

This principle drove the entire consolidation strategy:
- **Chrome plugin** = Infrastructure only (NO ArchiveResult)
- **Output plugins** = Each produces ONE distinct ArchiveResult (kept separate)

## Final Structure

### 1. Chrome Plugin (Infrastructure - No Output)

**Location:** `archivebox/plugins/chrome/`

This plugin provides shared Chrome infrastructure for other plugins. It manages the browser lifecycle but **produces NO ArchiveResult** - only infrastructure files in a single `chrome/` output directory.

**Consolidates these former plugins:**
- `chrome_session/` → Merged
- `chrome_navigate/` → Merged
- `chrome_cleanup/` → Merged
- `chrome_extensions/` → Utilities merged

**Hook Files:**
```
chrome/
├── on_Crawl__00_chrome_install_config.py  # Configure Chrome settings
├── on_Crawl__00_chrome_install.py         # Install Chrome binary
├── on_Crawl__30_chrome_launch.bg.js       # Launch Chrome (Crawl-level, bg)
├── on_Snapshot__20_chrome_tab.bg.js       # Open tab (Snapshot-level, bg)
├── on_Snapshot__30_chrome_navigate.js     # Navigate to URL (foreground)
├── on_Snapshot__45_chrome_tab_cleanup.py  # Close tab, kill bg hooks
├── chrome_extension_utils.js              # Extension utilities
├── config.json                            # Configuration
└── tests/test_chrome.py                   # Tests
```

**Output Directory (Infrastructure Only):**
```
chrome/
├── cdp_url.txt          # WebSocket URL for CDP connection
├── pid.txt              # Chrome process PID
├── target_id.txt          # Current tab target ID
├── page_loaded.txt      # Navigation completion marker
├── final_url.txt        # Final URL after redirects
├── navigation.json      # Navigation state (NEW)
└── hook.pid             # Background hook PIDs (for cleanup)
```

**New: navigation.json**

Tracks navigation state with wait condition and timing:
```json
{
  "waitUntil": "networkidle2",
  "elapsed": 1523,
  "url": "https://example.com",
  "finalUrl": "https://example.com/",
  "status": 200,
  "timestamp": "2025-12-27T22:15:30.123Z"
}
```

Fields:
- `waitUntil` - Wait condition: `networkidle0`, `networkidle2`, `domcontentloaded`, or `load`
- `elapsed` - Navigation time in milliseconds
- `url` - Original requested URL
- `finalUrl` - Final URL after redirects (success only)
- `status` - HTTP status code (success only)
- `error` - Error message (failure only)
- `timestamp` - ISO 8601 completion timestamp

### 2. Output Plugins (Each = One ArchiveResult)

These remain **SEPARATE** plugins because each produces a distinct output/ArchiveResult. Each plugin references `../chrome` for infrastructure.

#### consolelog Plugin
```
archivebox/plugins/consolelog/
└── on_Snapshot__21_consolelog.bg.js
```
- **Output:** `console.jsonl` (browser console messages)
- **Type:** Background hook (CDP listener)
- **References:** `../chrome` for CDP URL

#### ssl Plugin
```
archivebox/plugins/ssl/
└── on_Snapshot__23_ssl.bg.js
```
- **Output:** `ssl.jsonl` (SSL/TLS certificate details)
- **Type:** Background hook (CDP listener)
- **References:** `../chrome` for CDP URL

#### responses Plugin
```
archivebox/plugins/responses/
└── on_Snapshot__24_responses.bg.js
```
- **Output:** `responses/` directory with `index.jsonl` (network responses)
- **Type:** Background hook (CDP listener)
- **References:** `../chrome` for CDP URL

#### redirects Plugin
```
archivebox/plugins/redirects/
└── on_Snapshot__31_redirects.bg.js
```
- **Output:** `redirects.jsonl` (redirect chain)
- **Type:** Background hook (CDP listener)
- **References:** `../chrome` for CDP URL
- **Changed:** Converted to background hook, now uses CDP `Network.requestWillBeSent` to capture redirects from initial request

#### staticfile Plugin
```
archivebox/plugins/staticfile/
└── on_Snapshot__31_staticfile.bg.js
```
- **Output:** Downloaded static file (PDF, image, video, etc.)
- **Type:** Background hook (CDP listener)
- **References:** `../chrome` for CDP URL
- **Changed:** Converted from Python to JavaScript, now uses CDP to detect Content-Type from initial response and download via CDP

## What Changed

### 1. Plugin Consolidation
- Merged `chrome_session`, `chrome_navigate`, `chrome_cleanup`, `chrome_extensions` → `chrome/`
- Chrome plugin now has **single output directory**: `chrome/`
- All Chrome infrastructure hooks reference `.` (same directory)

### 2. Background Hook Conversions

**redirects Plugin:**
- **Before:** Ran AFTER navigation, reconnected to Chrome to check for redirects
- **After:** Background hook that sets up CDP listeners BEFORE navigation to capture redirects from initial request
- **Method:** Uses CDP `Network.requestWillBeSent` event with `redirectResponse` parameter

**staticfile Plugin:**
- **Before:** Python script that ran AFTER navigation, checked response headers
- **After:** Background JavaScript hook that sets up CDP listeners BEFORE navigation
- **Method:** Uses CDP `page.on('response')` to capture Content-Type from initial request
- **Language:** Converted from Python to JavaScript/Node.js for consistency

### 3. Navigation State Tracking
- **Added:** `navigation.json` file in `chrome/` output directory
- **Contains:** `waitUntil` condition and `elapsed` milliseconds
- **Purpose:** Track navigation performance and wait conditions for analysis

### 4. Cleanup
- **Deleted:** `chrome_session/on_CrawlEnd__99_chrome_cleanup.py` (manual cleanup hook)
- **Reason:** Automatic cleanup via state machines is sufficient
- **Verified:** Cleanup mechanisms in `core/models.py` and `crawls/models.py` work correctly

## Hook Execution Order

```
═══ CRAWL LEVEL ═══
  00. chrome_install_config.py    Configure Chrome settings
  00. chrome_install.py            Install Chrome binary
  20. chrome_launch.bg.js          Launch Chrome browser (STAYS RUNNING)

═══ PER-SNAPSHOT LEVEL ═══

Phase 1: PRE-NAVIGATION (Background hooks setup)
  20. chrome_tab.bg.js             Open new tab (STAYS ALIVE)
  21. consolelog.bg.js             Setup console listener (STAYS ALIVE)
  23. ssl.bg.js                    Setup SSL listener (STAYS ALIVE)
  24. responses.bg.js              Setup network response listener (STAYS ALIVE)
  31. redirects.bg.js              Setup redirect listener (STAYS ALIVE)
  31. staticfile.bg.js             Setup staticfile detector (STAYS ALIVE)

Phase 2: NAVIGATION (Foreground - synchronization point)
  30. chrome_navigate.js           Navigate to URL (BLOCKS until page loaded)
                                   ↓
                                   Writes navigation.json with waitUntil & elapsed
                                   Writes page_loaded.txt marker
                                   ↓
                                   All background hooks can now finalize

Phase 3: POST-NAVIGATION (Background hooks finalize)
  (All .bg hooks save their data and wait for cleanup signal)

Phase 4: OTHER EXTRACTORS (use loaded page)
  34. screenshot.js
  37. singlefile.js
  ... (other extractors that need loaded page)

Phase 5: CLEANUP
  45. chrome_tab_cleanup.py        Close tab
                                   Kill background hooks (SIGTERM → SIGKILL)
                                   Update ArchiveResults
```

## Background Hook Pattern

All `.bg.js` hooks follow this pattern:

1. **Setup:** Create CDP listeners BEFORE navigation
2. **Capture:** Collect data incrementally as events occur
3. **Write:** Save data to filesystem continuously
4. **Wait:** Keep process alive until SIGTERM
5. **Finalize:** On SIGTERM, emit final JSONL result to stdout
6. **Exit:** Clean exit with status code

**Key files written:**
- `hook.pid` - Process ID for cleanup mechanism
- Output files (e.g., `console.jsonl`, `ssl.jsonl`, etc.)

## Automatic Cleanup Mechanism

**Snapshot-level cleanup** (`core/models.py`):
```python
def cleanup(self):
    """Kill background hooks and close resources."""
    # Scan OUTPUT_DIR for hook.pid files
    # Send SIGTERM to processes
    # Wait for graceful exit
    # Send SIGKILL if process still alive
    # Update ArchiveResults to FAILED if needed
```

**Crawl-level cleanup** (`crawls/models.py`):
```python
def cleanup(self):
    """Kill Crawl-level background hooks (Chrome browser)."""
    # Similar pattern for Crawl-level resources
    # Kills Chrome launch process
```

**State machine integration:**
- Both `SnapshotMachine` and `CrawlMachine` call `cleanup()` when entering `sealed` state
- Ensures all background processes are cleaned up properly
- No manual cleanup hooks needed

## Directory References

**Crawl output structure:**
- Crawls output to: `users/{user_id}/crawls/{YYYYMMDD}/{crawl_id}/`
- Example: `users/1/crawls/20251227/abc-def-123/`
- Crawl-level plugins create subdirectories: `users/1/crawls/20251227/abc-def-123/chrome/`

**Snapshot output structure:**
- Snapshots output to: `archive/{timestamp}/`
- Snapshot-level plugins create subdirectories: `archive/{timestamp}/chrome/`, `archive/{timestamp}/consolelog/`, etc.

**Within chrome plugin:**
- Hooks use `.` or `OUTPUT_DIR` to reference the `chrome/` directory they're running in
- Example: `fs.writeFileSync(path.join(OUTPUT_DIR, 'navigation.json'), ...)`

**From output plugins to chrome (same snapshot):**
- Hooks use `../chrome` to reference Chrome infrastructure in same snapshot
- Example: `const CHROME_SESSION_DIR = '../chrome';`
- Used to read: `cdp_url.txt`, `target_id.txt`, `page_loaded.txt`

**From snapshot hooks to crawl chrome:**
- Snapshot hooks receive `CRAWL_OUTPUT_DIR` environment variable (set by hooks.py)
- Use: `path.join(process.env.CRAWL_OUTPUT_DIR, 'chrome')` to find crawl-level Chrome
- This allows snapshots to reuse the crawl's shared Chrome browser

**Navigation synchronization:**
- All hooks wait for `../chrome/page_loaded.txt` before finalizing
- This file is written by `chrome_navigate.js` after navigation completes

## Design Principles

1. **One ArchiveResult Per Plugin**
   - Each plugin produces exactly ONE output/ArchiveResult
   - Infrastructure plugins (like chrome) produce NO ArchiveResult

2. **Chrome as Infrastructure**
   - Provides shared CDP connection, PIDs, navigation state
   - No ArchiveResult output of its own
   - Single output directory for all infrastructure files

3. **Background Hooks for CDP**
   - Hooks that need CDP listeners BEFORE navigation are background (`.bg.js`)
   - They capture events from the initial request/response
   - Stay alive through navigation and cleanup

4. **Foreground for Synchronization**
   - `chrome_navigate.js` is foreground (not `.bg`)
   - Provides synchronization point - blocks until page loaded
   - All other hooks wait for its completion marker

5. **Automatic Cleanup**
   - State machines handle background hook cleanup
   - No manual cleanup hooks needed
   - SIGTERM for graceful exit, SIGKILL as backup

6. **Clear Separation**
   - Infrastructure vs outputs
   - One output directory per plugin
   - Predictable, maintainable architecture

## Benefits

✓ **Architectural Clarity** - Clear separation between infrastructure and outputs
✓ **Correct Output Model** - One ArchiveResult per plugin
✓ **Better Performance** - CDP listeners capture data from initial request
✓ **No Duplication** - Single Chrome infrastructure used by all
✓ **Proper Lifecycle** - Background hooks cleaned up automatically
✓ **Maintainable** - Easy to understand, debug, and extend
✓ **Consistent** - All background hooks follow same pattern
✓ **Observable** - Navigation state tracked for debugging

## Testing

Run tests:
```bash
sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/plugins/chrome/tests/ -v'
```

## Migration Notes

**For developers:**
- Chrome infrastructure is now in `chrome/` output dir (not `chrome_session/`)
- Reference `../chrome/cdp_url.txt` from output plugins
- Navigation marker is `../chrome/page_loaded.txt`
- Navigation details in `../chrome/navigation.json`

**For users:**
- No user-facing changes
- Output structure remains the same
- All extractors continue to work
