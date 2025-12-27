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

## Running Tests

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

## Test Writing Standards

### NO MOCKS - Real Tests Only
Tests must exercise real code paths:
- Create real SQLite databases with version-specific schemas
- Seed with realistic test data
- Run actual `python -m archivebox` commands via subprocess
- Query SQLite directly to verify results

**If something is hard to test**: Modify the implementation to make it easier to test, or fix the underlying issue. Never mock, skip, simulate, or exit early from a test because you can't get something working inside the test.

### NO SKIPS
Never use `@skip`, `skipTest`, or `pytest.mark.skip`. Every test must run. If a test is difficult, fix the code or test environment - don't disable the test.

### Strict Assertions
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

## Migration Testing

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

## Common Gotchas

### 1. File Permissions
New files created by root need permissions fixed for testuser:
```bash
chmod 644 archivebox/tests/test_*.py
```

### 2. DATA_DIR Environment Variable
ArchiveBox commands must run inside a data directory. Tests use temp directories - the `run_archivebox()` helper sets `DATA_DIR` automatically.

### 3. Extractors Disabled for Speed
Tests disable all extractors via environment variables for faster execution:
```python
env['SAVE_TITLE'] = 'False'
env['SAVE_FAVICON'] = 'False'
# ... etc
```

### 4. Timeout Settings
Use appropriate timeouts for migration tests (45s for init, 60s default).

### 5. Circular FK References in Schemas
SQLite handles circular references with `IF NOT EXISTS`. Order matters less than in other DBs.

## Architecture Notes

### Crawl Model (0.9.x)
- Crawl groups multiple Snapshots from a single `add` command
- Each `add` creates one Crawl with one or more Snapshots
- Seed model was removed - crawls now store URLs directly

### Migration Strategy
- Squashed migrations for clean installs
- Individual migrations recorded for upgrades from dev branch
- `replaces` attribute in squashed migrations lists what they replace

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

# InstalledBinary reuses the same field name and structure
class InstalledBinary(models.Model):
    overrides = models.JSONField(default=dict)  # Same name, same structure
```

**Example - BAD**:
```python
# Don't invent new names like custom_bin_cmds, installed_binary_overrides, etc.
class InstalledBinary(models.Model):
    custom_bin_cmds = models.JSONField(default=dict)  # ❌ New unique name
```

**Principle**: If you're storing the same conceptual data (e.g., `overrides`), use the same field name across all models and keep the internal structure identical. This makes the codebase predictable and reduces cognitive load.

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
