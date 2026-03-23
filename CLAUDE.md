# Claude Code Development Guide for ArchiveBox

## Quick Start

```bash
# Set up dev environment (always use uv, never pip directly)
uv sync --dev --all-extras

# Run tests as non-root user (required - ArchiveBox always refuses to run as root)
sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/ -v'
```

## Development Environment Setup

### Prerequisites
- Python 3.11+ (3.13 recommended)
- uv package manager
- A non-root user for running tests (e.g., `testuser`)

### Install Dependencies
```bash
uv sync --dev --all-extras  # Always use uv, never pip directly
```

### Activate Virtual Environment
```bash
source .venv/bin/activate
```

### Common Gotchas

#### File Permissions
New files created by root need permissions fixed for testuser:
```bash
chmod 644 archivebox/tests/test_*.py
```

#### DATA_DIR Environment Variable
ArchiveBox commands must run inside a data directory. Tests use temp directories - the `run_archivebox()` helper sets `DATA_DIR` automatically.

## Code Style Guidelines

### Naming Conventions for Grep-ability
Use consistent naming for everything to enable easy grep-ability and logical grouping:

**Principle**: Fewest unique names. If you must create a new unique name, make it grep and group well.

**Examples**:
```python
# Filesystem migration methods - all start with fs_
def fs_migration_needed() -> bool: ...
def fs_migrate() -> None: ...
def _fs_migrate_from_0_7_0_to_0_8_0() -> None: ...
def _fs_migrate_from_0_8_0_to_0_9_0() -> None: ...
def _fs_next_version(current: str) -> str: ...

# Logging methods - ALL must start with log_ or _log
def log_migration_start(snapshot_id: str) -> None: ...
def _log_error(message: str) -> None: ...
def log_validation_result(ok: bool, msg: str) -> None: ...
```

**Rules**:
- Group related functions with common prefixes
- Use `_` prefix for internal/private helpers within the same family
- ALL logging-related methods MUST start with `log_` or `_log`
- Search for all migration functions: `grep -r "def.*fs_.*(" archivebox/`
- Search for all logging: `grep -r "def.*log_.*(" archivebox/`

### Minimize Unique Names and Data Structures
**Do not invent new data structures, variable names, or keys if possible.** Try to use existing field names and data structures exactly to keep the total unique data structures and names in the codebase to an absolute minimum.

**Example - GOOD**:
```python
# Binary has overrides field
binary = Binary(overrides={'TIMEOUT': '60s'})

# Binary reuses the same field name and structure
class Binary(models.Model):
    overrides = models.JSONField(default=dict)  # Same name, same structure
```

**Example - BAD**:
```python
# Don't invent new names like custom_bin_cmds, binary_overrides, etc.
class Binary(models.Model):
    custom_bin_cmds = models.JSONField(default=dict)  # ❌ New unique name
```

**Principle**: If you're storing the same conceptual data (e.g., `overrides`), use the same field name across all models and keep the internal structure identical. This makes the codebase predictable and reduces cognitive load.

## Testing

### CRITICAL: Never Run as Root
ArchiveBox has a root check that prevents running as root user. All ArchiveBox commands (including tests) must run as non-root user inside a data directory:

```bash
# Run all migration tests
sudo -u testuser bash -c 'source /path/to/.venv/bin/activate && python -m pytest archivebox/tests/test_migrations_*.py -v'

# Run specific test file
sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_migrations_08_to_09.py -v'

# Run single test
sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_migrations_fresh.py::TestFreshInstall::test_init_creates_database -xvs'
```

### Test File Structure
```
archivebox/tests/
├── test_migrations_helpers.py    # Schemas, seeding functions, verification helpers
├── test_migrations_fresh.py      # Fresh install tests
├── test_migrations_04_to_09.py   # 0.4.x → 0.9.x migration tests
├── test_migrations_07_to_09.py   # 0.7.x → 0.9.x migration tests
└── test_migrations_08_to_09.py   # 0.8.x → 0.9.x migration tests
```

### Test Writing Standards

#### NO MOCKS - Real Tests Only
Tests must exercise real code paths:
- Create real SQLite databases with version-specific schemas
- Seed with realistic test data
- Run actual `python -m archivebox` commands via subprocess
- Query SQLite directly to verify results

**If something is hard to test**: Modify the implementation to make it easier to test, or fix the underlying issue. Never mock, skip, simulate, or exit early from a test because you can't get something working inside the test.

#### NO SKIPS
Never use `@skip`, `skipTest`, or `pytest.mark.skip`. Every test must run. If a test is difficult, fix the code or test environment - don't disable the test.

#### Strict Assertions
- `init` command must return exit code 0 (not `[0, 1]`)
- Verify ALL data is preserved, not just "at least one"
- Use exact counts (`==`) not loose bounds (`>=`)

### Example Test Pattern
```python
def test_migration_preserves_snapshots(self):
    """Migration should preserve all snapshots."""
    result = run_archivebox(self.work_dir, ['init'], timeout=45)
    self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

    ok, msg = verify_snapshot_count(self.db_path, expected_count)
    self.assertTrue(ok, msg)
```

### Testing Gotchas

#### Extractors Disabled for Speed
Tests disable all extractors via environment variables for faster execution:
```python
env['SAVE_TITLE'] = 'False'
env['SAVE_FAVICON'] = 'False'
# ... etc
```

#### Timeout Settings
Use appropriate timeouts for migration tests (45s for init, 60s default).

### Plugin Testing & Code Coverage

**Target: 80-90% coverage** for critical plugins (screenshot, chrome, singlefile, dom)

```bash
# Run plugin tests with coverage (both Python + JavaScript)
bash bin/test_plugins.sh screenshot

# View coverage reports
bash bin/test_plugins.sh --coverage-report
# Or individual reports:
coverage report --show-missing --include='archivebox/plugins/*' --omit='*/tests/*'
```

#### Plugin Test Structure

Tests are **completely isolated** from ArchiveBox - they replicate production directory structure in temp dirs:

```python
# Correct production paths:
# Crawl:    DATA_DIR/users/{username}/crawls/YYYYMMDD/example.com/{crawl-id}/{plugin}/
# Snapshot: DATA_DIR/users/{username}/snapshots/YYYYMMDD/example.com/{snapshot-uuid}/{plugin}/

with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir)

    # Crawl-level plugin (e.g., chrome launcher)
    crawl_dir = data_dir / 'users' / 'testuser' / 'crawls' / '20240101' / 'example.com' / 'crawl-123'
    chrome_dir = crawl_dir / 'chrome'
    chrome_dir.mkdir(parents=True)

    # Snapshot-level plugin (e.g., screenshot)
    snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-456'
    screenshot_dir = snapshot_dir / 'screenshot'
    screenshot_dir.mkdir(parents=True)

    # Run hook in its output directory
    result = subprocess.run(
        ['node', str(SCREENSHOT_HOOK), '--url=https://example.com'],
        cwd=str(screenshot_dir),
        env={**get_test_env(), 'EXTRA_CONTEXT': '{"snapshot_id":"snap-456"}'},
        capture_output=True,
        timeout=120
    )
```

#### Coverage Improvement Loop

To improve from ~20% to 80%+:

1. **Run tests**: `bash bin/test_plugins.sh screenshot` → Shows: `19.1% (13/68 ranges)`
2. **Identify gaps**: Check hook file for untested paths (session connection vs fallback, config branches, error cases)
3. **Add tests**: Test both execution paths (connect to session + launch own browser), skip conditions, error cases, config variations
4. **Verify**: Re-run tests → Should show: `85%+ (58+/68 ranges)`

**Critical**: JavaScript hooks have TWO paths that both must be tested (connect to session ~50% + launch browser ~30% + shared ~20%). Testing only one path = max 50% coverage possible!

## Database Migrations

### Generate and Apply Migrations
```bash
# Generate migrations (run from archivebox subdirectory)
cd archivebox
./manage.py makemigrations

# Apply migrations to test database
cd data/
archivebox init
```

### Schema Versions
- **0.4.x**: First Django version. Tags as comma-separated string, no ArchiveResult model
- **0.7.x**: Tag model with M2M, ArchiveResult model, AutoField PKs
- **0.8.x**: Crawl/Seed models, UUID PKs, status fields, depth/retry_at
- **0.9.x**: Seed model removed, seed_id FK removed from Crawl

### Testing a Migration Path
1. Create SQLite DB with source version schema (from `test_migrations_helpers.py`)
2. Seed with realistic test data using `seed_0_X_data()`
3. Run `archivebox init` to trigger migrations
4. Verify data preservation with `verify_*` functions
5. Test CLI commands work post-migration (`status`, `list`, `add`, etc.)

### Squashed Migrations
When testing 0.8.x (dev branch), you must record ALL replaced migrations:
```python
# The squashed migration replaces these - all must be recorded
('core', '0023_alter_archiveresult_options_archiveresult_abid_and_more'),
('core', '0024_auto_20240513_1143'),
# ... all 52 migrations from 0023-0074 ...
('core', '0023_new_schema'),  # Also record the squashed migration itself
```

### Migration Strategy
- Squashed migrations for clean installs
- Individual migrations recorded for upgrades from dev branch
- `replaces` attribute in squashed migrations lists what they replace

### Migration Gotchas

#### Circular FK References in Schemas
SQLite handles circular references with `IF NOT EXISTS`. Order matters less than in other DBs.

## Plugin System Architecture

### Plugin Dependency Rules

Like other plugins, chrome plugins **ARE NOT ALLOWED TO DEPEND ON ARCHIVEBOX OR DJANGO**.
However, they are allowed to depend on two shared files ONLY:
- `archivebox/plugins/chrome/chrome_utils.js` ← source of truth API for all basic chrome ops
- `archivebox/plugins/chrome/tests/chrome_test_utils.py` ← use for your tests, do not implement launching/killing/pid files/cdp/etc. in python, just extend this file as needed.

### Chrome-Dependent Plugins

Many plugins depend on Chrome/Chromium via CDP (Chrome DevTools Protocol). When checking for script name references or debugging Chrome-related issues, check these plugins:

**Main puppeteer-based chrome installer + launcher plugin**:
- `chrome` - Core Chrome integration (CDP, launch, navigation)

**Metadata extraction using chrome/chrome_utils.js / CDP**:
- `dns` - DNS resolution info
- `ssl` - SSL certificate info
- `headers` - HTTP response headers
- `redirects` - Capture redirect chains
- `staticfile` - Direct file downloads (e.g. if the url itself is a .png, .exe, .zip, etc.)
- `responses` - Capture network responses
- `consolelog` - Capture console.log output
- `title` - Extract page title
- `accessibility` - Extract accessibility tree
- `seo` - Extract SEO metadata

**Extensions installed using chrome/chrome_utils.js / controlled using CDP**:
- `ublock` - uBlock Origin ad blocking
- `istilldontcareaboutcookies` - Cookie banner dismissal
- `twocaptcha` - 2captcha CAPTCHA solver integration

**Page-alteration plugins to prepare the content for archiving**:
- `modalcloser` - Modal dialog dismissal
- `infiniscroll` - Infinite scroll handler

**Main Extractor Outputs**:
- `dom` - DOM snapshot extraction
- `pdf` - Generate PDF snapshots
- `screenshot` - Generate screenshots
- `singlefile` - SingleFile archival, can be single-file-cli that launches chrome, or singlefile extension running inside chrome

**Crawl URL parsers** (post-process dom.html, singlefile.html, staticfile, responses, headers, etc. for URLs to re-emit as new queued Snapshots during recursive crawling):
- `parse_dom_outlinks` - Extract outlinks from DOM (special, uses CDP to directly query browser)
- `parse_html_urls` - Parse URLs from HTML (doesn't use chrome directly, just reads dom.html)
- `parse_jsonl_urls` - Parse URLs from JSONL (doesn't use chrome directly, just reads dom.html)
- `parse_netscape_urls` - Parse Netscape bookmark format (doesn't use chrome directly, just reads dom.html)

### Finding Chrome-Dependent Plugins

```bash
# Find all files containing "chrom" (case-insensitive)
grep -ri "chrom" archivebox/plugins/*/on_*.* --include="*.*" 2>/dev/null | cut -d: -f1 | sort -u

# Or get just the plugin names
grep -ri "chrom" archivebox/plugins/*/on_*.* --include="*.*" 2>/dev/null | cut -d/ -f3 | sort -u
```

**Note**: This list may not be complete. Always run the grep command above when checking for Chrome-related script references or debugging Chrome integration issues.

## Architecture Notes

### Crawl Model (0.9.x)
- Crawl groups multiple Snapshots from a single `add` command
- Each `add` creates one Crawl with one or more Snapshots
- Seed model was removed - crawls now store URLs directly

## Code Coverage

### Overview

Coverage tracking is enabled for passive collection across all contexts:
- Unit tests (pytest)
- Integration tests
- Dev server (manual testing)
- CLI usage

Coverage data accumulates in `.coverage` file and can be viewed/analyzed to find dead code.

### Install Coverage Tools

```bash
uv sync --dev  # Installs pytest-cov and coverage
```

### Running with Coverage

#### Unit Tests
```bash
# Run tests with coverage
pytest --cov=archivebox --cov-report=term archivebox/tests/

# Or run specific test file
pytest --cov=archivebox --cov-report=term archivebox/tests/test_migrations_08_to_09.py
```

#### Dev Server with Coverage
```bash
# Start dev server with coverage tracking
coverage run --parallel-mode -m archivebox server

# Or CLI commands
coverage run --parallel-mode -m archivebox init
coverage run --parallel-mode -m archivebox add https://example.com
```

#### Manual Testing (Always-On)
To enable coverage during ALL Python executions (passive tracking):

```bash
# Option 1: Use coverage run wrapper
coverage run --parallel-mode -m archivebox [command]

# Option 2: Set environment variable (tracks everything)
export COVERAGE_PROCESS_START=pyproject.toml
# Now all Python processes will track coverage
archivebox server
archivebox add https://example.com
```

### Viewing Coverage

#### Text Report (Quick View)
```bash
# Combine all parallel coverage data
coverage combine

# View summary
coverage report

# View detailed report with missing lines
coverage report --show-missing

# View specific file
coverage report --include="archivebox/core/models.py" --show-missing
```

#### JSON Report (LLM-Friendly)
```bash
# Generate JSON report
coverage json

# View the JSON
cat coverage.json | jq '.files | keys'  # List all files

# Find files with low coverage
cat coverage.json | jq -r '.files | to_entries[] | select(.value.summary.percent_covered < 50) | "\(.key): \(.value.summary.percent_covered)%"'

# Find completely uncovered files (dead code candidates)
cat coverage.json | jq -r '.files | to_entries[] | select(.value.summary.percent_covered == 0) | .key'

# Get missing lines for a specific file
cat coverage.json | jq '.files["archivebox/core/models.py"].missing_lines'
```

#### HTML Report (Visual)
```bash
# Generate interactive HTML report
coverage html

# Open in browser
open htmlcov/index.html
```

### Isolated Runs

To measure coverage for specific scenarios:

```bash
# 1. Reset coverage data
coverage erase

# 2. Run your isolated test/scenario
pytest --cov=archivebox archivebox/tests/test_migrations_fresh.py
# OR
coverage run --parallel-mode -m archivebox add https://example.com

# 3. View results
coverage combine
coverage report --show-missing

# 4. Optionally export for analysis
coverage json
```

### Finding Dead Code

```bash
# 1. Run comprehensive tests + manual testing to build coverage
pytest --cov=archivebox archivebox/tests/
coverage run --parallel-mode -m archivebox server  # Use the app manually
coverage combine

# 2. Find files with 0% coverage (strong dead code candidates)
coverage json
cat coverage.json | jq -r '.files | to_entries[] | select(.value.summary.percent_covered == 0) | .key'

# 3. Find files with <10% coverage (likely dead code)
cat coverage.json | jq -r '.files | to_entries[] | select(.value.summary.percent_covered < 10) | "\(.key): \(.value.summary.percent_covered)%"' | sort -t: -k2 -n

# 4. Generate detailed report for analysis
coverage report --show-missing > coverage_report.txt
```

### Tips

- **Parallel mode** (`--parallel-mode`): Allows multiple processes to track coverage simultaneously without conflicts
- **Combine**: Always run `coverage combine` before viewing reports to merge parallel data
- **Reset**: Use `coverage erase` to start fresh for isolated measurements
- **Branch coverage**: Enabled by default - tracks if both branches of if/else are executed
- **Exclude patterns**: Config in `pyproject.toml` excludes tests, migrations, type stubs

## Debugging Tips

### Check Migration State
```bash
sqlite3 /path/to/index.sqlite3 "SELECT app, name FROM django_migrations WHERE app='core' ORDER BY id;"
```

### Check Table Schema
```bash
sqlite3 /path/to/index.sqlite3 "PRAGMA table_info(core_snapshot);"
```

### Verbose Test Output
```bash
sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_migrations_08_to_09.py -xvs 2>&1 | head -200'
```

### Kill Zombie Chrome Processes
```bash
./bin/kill_chrome.sh
```
