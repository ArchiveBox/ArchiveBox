# ArchiveBox Hook Script Concurrency & Execution Plan

## Overview

Snapshot.run() should enforce that snapshot hooks are run in **10 discrete, sequential "steps"**: `0*`, `1*`, `2*`, `3*`, `4*`, `5*`, `6*`, `7*`, `8*`, `9*`.

For every discovered hook script, ArchiveBox should create an ArchiveResult in `queued` state, then manage running them using `retry_at` and inline logic to enforce this ordering.

## Hook Numbering Convention

Hooks scripts are numbered `00` to `99` to control:
- **First digit (0-9)**: Which step they are part of
- **Second digit (0-9)**: Order within that step

Hook scripts are launched **strictly sequentially** based on their filename alphabetical order, and run in sets of several per step before moving on to the next step.

**Naming Format:**
```
on_{ModelName}__{run_order}_{human_readable_description}[.bg].{ext}
```

**Examples:**
```
on_Snapshot__00_this_would_run_first.sh
on_Snapshot__05_start_ytdlp_download.bg.sh
on_Snapshot__10_chrome_tab_opened.js
on_Snapshot__50_screenshot.js
on_Snapshot__53_media.bg.py
```

## Background (.bg) vs Foreground Scripts

### Foreground Scripts (no .bg suffix)
- Run sequentially within their step
- Block step progression until they exit
- Should exit naturally when work is complete
- Get killed with SIGTERM if they exceed their `PLUGINNAME_TIMEOUT`

### Background Scripts (.bg suffix)
- Spawned and allowed to continue running
- Do NOT block step progression
- Run until **their own `PLUGINNAME_TIMEOUT` is reached** (not until step 99)
- Get polite SIGTERM when timeout expires, then SIGKILL 60s later if not exited
- Must implement their own concurrency control using filesystem (semaphore files, locks, etc.)
- Should exit naturally when work is complete (best case)

**Important:** If a .bg script starts at step 05 with `MEDIA_TIMEOUT=3600s`, it gets the full 3600s regardless of when step 99 completes. It runs on its own timeline.

## Execution Step Guidelines

These are **naming conventions and guidelines**, not enforced checkpoints. They provide semantic organization for plugin ordering:

### Step 0: Pre-Setup
```
00-09: Initial setup, validation, feature detection
```

### Step 1: Chrome Launch & Tab Creation
```
10-19: Browser/tab lifecycle setup
- Chrome browser launch
- Tab creation and CDP connection
```

### Step 2: Navigation & Settlement
```
20-29: Page loading and settling
- Navigate to URL
- Wait for page load
- Initial response capture (responses, ssl, consolelog as .bg listeners)
```

### Step 3: Page Adjustment
```
30-39: DOM manipulation before archiving
- Hide popups/banners
- Solve captchas
- Expand comments/details sections
- Inject custom CSS/JS
- Accessibility modifications
```

### Step 4: Ready for Archiving
```
40-49: Final pre-archiving checks
- Verify page is fully adjusted
- Wait for any pending modifications
```

### Step 5: DOM Extraction (Sequential, Non-BG)
```
50-59: Extractors that need exclusive DOM access
- singlefile (MUST NOT be .bg)
- screenshot (MUST NOT be .bg)
- pdf (MUST NOT be .bg)
- dom (MUST NOT be .bg)
- title
- headers
- readability
- mercury

These MUST run sequentially as they temporarily modify the DOM
during extraction, then revert it. Running in parallel would corrupt results.
```

### Step 6: Post-DOM Extraction
```
60-69: Extractors that don't need DOM or run on downloaded files
- wget
- git
- media (.bg - can run for hours)
- gallerydl (.bg)
- forumdl (.bg)
- papersdl (.bg)
```

### Step 7: Chrome Cleanup
```
70-79: Browser/tab teardown
- Close tabs
- Cleanup Chrome resources
```

### Step 8: Post-Processing
```
80-89: Reprocess outputs from earlier extractors
- OCR of images
- Audio/video transcription
- URL parsing from downloaded content (rss, html, json, txt, csv, md)
- LLM analysis/summarization of outputs
```

### Step 9: Indexing & Finalization
```
90-99: Save to indexes and finalize
- Index text content to Sonic/SQLite FTS
- Create symlinks
- Generate merkle trees
- Final status updates
```

## Hook Script Interface

### Input: CLI Arguments (NOT stdin)
Hooks receive configuration as CLI flags (CSV or JSON-encoded):

```bash
--url="https://example.com"
--snapshot-id="1234-5678-uuid"
--config='{"some_key": "some_value"}'
--plugins=git,media,favicon,title
--timeout=50
--enable-something
```

### Input: Environment Variables
All configuration comes from env vars, defined in `plugin_dir/config.json` JSONSchema:

```bash
WGET_BINARY=/usr/bin/wget
WGET_TIMEOUT=60
WGET_USER_AGENT="Mozilla/5.0..."
WGET_EXTRA_ARGS="--no-check-certificate"
SAVE_WGET=True
```

**Required:** Every plugin must support `PLUGINNAME_TIMEOUT` for self-termination.

### Output: Filesystem (CWD)
Hooks read/write files to:
- `$CWD`: Their own output subdirectory (e.g., `archive/snapshots/{id}/wget/`)
- `$CWD/..`: Parent directory (to read outputs from other hooks)

This allows hooks to:
- Access files created by other hooks
- Keep their outputs separate by default
- Use semaphore files for coordination (if needed)

### Output: JSONL to stdout
Hooks emit one JSONL line per database record they want to create or update:

```jsonl
{"type": "Tag", "name": "sci-fi"}
{"type": "ArchiveResult", "id": "1234-uuid", "status": "succeeded", "output_str": "wget/index.html"}
{"type": "Snapshot", "id": "5678-uuid", "title": "Example Page"}
```

See `archivebox/misc/jsonl.py` and model `from_json()` / `from_jsonl()` methods for full list of supported types and fields.

### Output: stderr for Human Logs
Hooks should emit human-readable output or debug info to **stderr**. There are no guarantees this will be persisted long-term. Use stdout JSONL or filesystem for outputs that matter.

### Cleanup: Delete Cruft
If hooks emit no meaningful long-term outputs, they should delete any temporary files themselves to avoid wasting space. However, the ArchiveResult DB row should be kept so we know:
- It doesn't need to be retried
- It isn't missing
- What happened (status, error message)

### Signal Handling: SIGINT/SIGTERM
Hooks are expected to listen for polite `SIGINT`/`SIGTERM` and finish hastily, then exit cleanly. Beyond that, they may be `SIGKILL'd` at ArchiveBox's discretion.

**If hooks double-fork or spawn long-running processes:** They must output a `.pid` file in their directory so zombies can be swept safely.

## Hook Failure Modes & Retry Logic

Hooks can fail in several ways. ArchiveBox handles each differently:

### 1. Soft Failure (Record & Don't Retry)
**Exit:** `0` (success)
**JSONL:** `{"type": "ArchiveResult", "status": "failed", "output_str": "404 Not Found"}`

This means: "I ran successfully, but the resource wasn't available." Don't retry this.

**Use cases:**
- 404 errors
- Content not available
- Feature not applicable to this URL

### 2. Hard Failure / Temporary Error (Retry Later)
**Exit:** Non-zero (1, 2, etc.)
**JSONL:** None (or incomplete)

This means: "Something went wrong, I couldn't complete." Treat this ArchiveResult as "missing" and set `retry_at` for later.

**Use cases:**
- 500 server errors
- Network timeouts
- Binary not found / crashed
- Transient errors

**Behavior:**
- ArchiveBox sets `retry_at` on the ArchiveResult
- Hook will be retried during next `archivebox update`

### 3. Partial Success (Update & Continue)
**Exit:** Non-zero
**JSONL:** Partial records emitted before crash

**Behavior:**
- Update ArchiveResult with whatever was emitted
- Mark remaining work as "missing" with `retry_at`

### 4. Success (Record & Continue)
**Exit:** `0`
**JSONL:** `{"type": "ArchiveResult", "status": "succeeded", "output_str": "output/file.html"}`

This is the happy path.

### Error Handling Rules

- **DO NOT skip hooks** based on failures
- **Continue to next hook** regardless of foreground or background failures
- **Update ArchiveResults** with whatever information is available
- **Set retry_at** for "missing" or temporarily-failed hooks
- **Let background scripts continue** even if foreground scripts fail

## File Structure

```
archivebox/plugins/{plugin_name}/
├── config.json              # JSONSchema: env var config options
├── binaries.jsonl           # Runtime dependencies: apt|brew|pip|npm|env
├── on_Snapshot__XX_name.py  # Hook script (foreground)
├── on_Snapshot__XX_name.bg.py  # Hook script (background)
└── tests/
    └── test_name.py
```

## Implementation Checklist

### Phase 1: Renumber Existing Hooks ✅
- [ ] Renumber DOM extractors to 50-59 range
- [ ] Ensure pdf/screenshot are NOT .bg (need sequential access)
- [ ] Ensure media (ytdlp) IS .bg (can run for hours)
- [ ] Add step comments to each plugin for clarity

### Phase 2: Timeout Consistency ✅
- [x] All plugins support `PLUGINNAME_TIMEOUT` env var
- [x] All plugins fall back to generic `TIMEOUT` env var
- [x] Background scripts handle SIGTERM gracefully (or exit naturally)

### Phase 3: Refactor Snapshot.run()
- [ ] Parse hook filenames to extract step number (first digit)
- [ ] Group hooks by step (0-9)
- [ ] Run each step sequentially
- [ ] Within each step:
  - [ ] Launch foreground hooks sequentially
  - [ ] Launch .bg hooks and track PIDs
  - [ ] Wait for foreground hooks to complete before next step
- [ ] Track .bg script timeouts independently
- [ ] Send SIGTERM to .bg scripts when their timeout expires
- [ ] Send SIGKILL 60s after SIGTERM if not exited

### Phase 4: ArchiveResult Management
- [ ] Create one ArchiveResult per hook (not per plugin)
- [ ] Set initial state to `queued`
- [ ] Update state based on JSONL output and exit code
- [ ] Set `retry_at` for hooks that exit non-zero with no JSONL
- [ ] Don't retry hooks that emit `{"status": "failed"}`

### Phase 5: JSONL Streaming
- [ ] Parse stdout JSONL line-by-line during hook execution
- [ ] Create/update DB rows as JSONL is emitted (streaming mode)
- [ ] Handle partial JSONL on hook crash

### Phase 6: Zombie Process Management
- [ ] Read `.pid` files from hook output directories
- [ ] Sweep zombies on cleanup
- [ ] Handle double-forked processes correctly

## Migration Path

### Backward Compatibility
During migration, support both old and new numbering:
1. Run hooks numbered 00-99 in step order
2. Run unnumbered hooks last (step 9) for compatibility
3. Log warnings for unnumbered hooks
4. Eventually require all hooks to be numbered

### Renumbering Map

**Current → New:**
```
git/on_Snapshot__12_git.py                    → git/on_Snapshot__62_git.py
media/on_Snapshot__51_media.py                → media/on_Snapshot__63_media.bg.py
gallerydl/on_Snapshot__52_gallerydl.py        → gallerydl/on_Snapshot__64_gallerydl.bg.py
forumdl/on_Snapshot__53_forumdl.py            → forumdl/on_Snapshot__65_forumdl.bg.py
papersdl/on_Snapshot__54_papersdl.py          → papersdl/on_Snapshot__66_papersdl.bg.py

readability/on_Snapshot__52_readability.py    → readability/on_Snapshot__55_readability.py
mercury/on_Snapshot__53_mercury.py            → mercury/on_Snapshot__56_mercury.py

singlefile/on_Snapshot__37_singlefile.py      → singlefile/on_Snapshot__50_singlefile.py
screenshot/on_Snapshot__34_screenshot.js      → screenshot/on_Snapshot__51_screenshot.js
pdf/on_Snapshot__35_pdf.js                    → pdf/on_Snapshot__52_pdf.js
dom/on_Snapshot__36_dom.js                    → dom/on_Snapshot__53_dom.js
title/on_Snapshot__32_title.js                → title/on_Snapshot__54_title.js
headers/on_Snapshot__33_headers.js            → headers/on_Snapshot__55_headers.js

wget/on_Snapshot__50_wget.py                  → wget/on_Snapshot__61_wget.py
```

## Testing Strategy

### Unit Tests
- Test hook ordering (00-99)
- Test step grouping (first digit)
- Test .bg vs foreground execution
- Test timeout enforcement
- Test JSONL parsing
- Test failure modes & retry_at logic

### Integration Tests
- Test full Snapshot.run() with mixed hooks
- Test .bg scripts running beyond step 99
- Test zombie process cleanup
- Test graceful SIGTERM handling
- Test concurrent .bg script coordination

### Performance Tests
- Measure overhead of per-hook ArchiveResults
- Test with 50+ concurrent .bg scripts
- Test filesystem contention with many hooks

## Open Questions

### Q: Should we provide semaphore utilities?
**A:** No. Keep plugins decoupled. Let them use simple filesystem coordination if needed.

### Q: What happens if ArchiveResult table gets huge?
**A:** We can delete old successful ArchiveResults periodically, or archive them to cold storage. The important data is in the filesystem outputs.

### Q: Should naturally-exiting .bg scripts still be .bg?
**A:** Yes. The .bg suffix means "don't block step progression," not "run until step 99." Natural exit is the best case.

## Examples

### Foreground Hook (Sequential DOM Access)
```python
#!/usr/bin/env python3
# archivebox/plugins/screenshot/on_Snapshot__51_screenshot.js

# Runs at step 5, blocks step progression until complete
# Gets killed if it exceeds SCREENSHOT_TIMEOUT

timeout = get_env_int('SCREENSHOT_TIMEOUT') or get_env_int('TIMEOUT', 60)

try:
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode == 0:
        print(json.dumps({
            "type": "ArchiveResult",
            "status": "succeeded",
            "output_str": "screenshot.png"
        }))
        sys.exit(0)
    else:
        # Temporary failure - will be retried
        sys.exit(1)
except subprocess.TimeoutExpired:
    # Timeout - will be retried
    sys.exit(1)
```

### Background Hook (Long-Running Download)
```python
#!/usr/bin/env python3
# archivebox/plugins/media/on_Snapshot__63_media.bg.py

# Runs at step 6, doesn't block step progression
# Gets full MEDIA_TIMEOUT (e.g., 3600s) regardless of when step 99 completes

timeout = get_env_int('YTDLP_TIMEOUT') or get_env_int('MEDIA_TIMEOUT') or get_env_int('TIMEOUT', 3600)

try:
    result = subprocess.run(['yt-dlp', url], capture_output=True, timeout=timeout)
    if result.returncode == 0:
        print(json.dumps({
            "type": "ArchiveResult",
            "status": "succeeded",
            "output_str": "media/"
        }))
        sys.exit(0)
    else:
        # Hard failure - don't retry
        print(json.dumps({
            "type": "ArchiveResult",
            "status": "failed",
            "output_str": "Video unavailable"
        }))
        sys.exit(0)  # Exit 0 to record the failure
except subprocess.TimeoutExpired:
    # Timeout - will be retried
    sys.exit(1)
```

### Background Hook with Natural Exit
```javascript
#!/usr/bin/env node
// archivebox/plugins/ssl/on_Snapshot__23_ssl.bg.js

// Sets up listener, captures SSL info, then exits naturally
// No SIGTERM handler needed - already exits when done

async function main() {
    const page = await connectToChrome();

    // Set up listener
    page.on('response', async (response) => {
        const securityDetails = response.securityDetails();
        if (securityDetails) {
            fs.writeFileSync('ssl.json', JSON.stringify(securityDetails));
        }
    });

    // Wait for navigation (done by other hook)
    await waitForNavigation();

    // Emit result
    console.log(JSON.stringify({
        type: 'ArchiveResult',
        status: 'succeeded',
        output_str: 'ssl.json'
    }));

    process.exit(0);  // Natural exit - no await indefinitely
}

main().catch(e => {
    console.error(`ERROR: ${e.message}`);
    process.exit(1);  // Will be retried
});
```

## Summary

This plan provides:
- ✅ Clear execution ordering (10 steps, 00-99 numbering)
- ✅ Async support (.bg suffix)
- ✅ Independent timeout control per plugin
- ✅ Flexible failure handling & retry logic
- ✅ Streaming JSONL output for DB updates
- ✅ Simple filesystem-based coordination
- ✅ Backward compatibility during migration

The main implementation work is refactoring `Snapshot.run()` to enforce step ordering and manage .bg script lifecycles. Plugin renumbering is straightforward mechanical work.
