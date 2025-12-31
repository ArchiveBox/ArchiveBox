# ArchiveBox CLI Pipeline Architecture

## Overview

This plan implements a JSONL-based CLI pipeline for ArchiveBox, enabling Unix-style piping between commands:

```bash
archivebox crawl create URL | archivebox snapshot create | archivebox archiveresult create | archivebox run
```

## Design Principles

1. **Maximize model method reuse**: Use `.to_json()`, `.from_json()`, `.to_jsonl()`, `.from_jsonl()` everywhere
2. **Pass-through behavior**: All commands output input records + newly created records (accumulating pipeline)
3. **Create-or-update**: Commands create records if they don't exist, update if ID matches existing
4. **Auto-cascade**: `archivebox run` automatically creates Snapshots from Crawls and ArchiveResults from Snapshots
5. **Generic filtering**: Implement filters as functions that take queryset → return queryset
6. **Minimal code**: Extract duplicated `apply_filters()` to shared module

---

## Real-World Use Cases

These examples demonstrate the power of the JSONL piping architecture. Note: `archivebox run`
auto-cascades (Crawl → Snapshots → ArchiveResults), so intermediate commands are only needed
when you want to customize behavior at that stage.

### 1. Basic Archive
```bash
# Simple URL archive (run auto-creates snapshots and archive results)
archivebox crawl create https://example.com | archivebox run

# Multiple URLs from a file
archivebox crawl create < urls.txt | archivebox run

# With depth crawling (follow links)
archivebox crawl create --depth=2 https://docs.python.org | archivebox run
```

### 2. Retry Failed Extractions
```bash
# Retry all failed extractions
archivebox archiveresult list --status=failed | archivebox run

# Retry only failed PDFs
archivebox archiveresult list --status=failed --plugin=pdf | archivebox run

# Retry failed items from a specific domain (jq filter)
archivebox snapshot list --status=queued \
  | jq 'select(.url | contains("nytimes.com"))' \
  | archivebox run
```

### 3. Import Bookmarks from Pinboard (jq)
```bash
# Fetch Pinboard bookmarks and archive them
curl -s "https://api.pinboard.in/v1/posts/all?format=json&auth_token=$TOKEN" \
  | jq -c '.[] | {url: .href, tags_str: .tags, title: .description}' \
  | archivebox crawl create \
  | archivebox run
```

### 4. Filter and Process with jq
```bash
# Archive only GitHub repository root pages (not issues, PRs, etc.)
archivebox snapshot list \
  | jq 'select(.url | test("github\\.com/[^/]+/[^/]+/?$"))' \
  | archivebox run

# Find snapshots with specific tag pattern
archivebox snapshot list \
  | jq 'select(.tags_str | contains("research"))' \
  | archivebox run
```

### 5. Selective Extraction (Screenshots Only)
```bash
# Create only screenshot extractions for queued snapshots
archivebox snapshot list --status=queued \
  | archivebox archiveresult create --plugin=screenshot \
  | archivebox run

# Re-run singlefile on everything that was skipped
archivebox archiveresult list --plugin=singlefile --status=skipped \
  | archivebox archiveresult update --status=queued \
  | archivebox run
```

### 6. Bulk Tag Management
```bash
# Tag all Twitter/X URLs
archivebox snapshot list --url__icontains=twitter.com \
  | archivebox snapshot update --tag=twitter

# Tag all URLs from today's crawl
archivebox crawl list --created_at__gte=$(date +%Y-%m-%d) \
  | archivebox snapshot list \
  | archivebox snapshot update --tag=daily-$(date +%Y%m%d)
```

### 7. Deep Documentation Crawl
```bash
# Mirror documentation site (depth=3 follows links 3 levels deep)
archivebox crawl create --depth=3 https://docs.djangoproject.com/en/4.2/ \
  | archivebox run

# Crawl with custom tag
archivebox crawl create --depth=2 --tag=python-docs https://docs.python.org/3/ \
  | archivebox run
```

### 8. RSS Feed Monitoring
```bash
# Archive all items from an RSS feed
curl -s "https://hnrss.org/frontpage" \
  | grep -oP '<link>\K[^<]+' \
  | archivebox crawl create --tag=hackernews \
  | archivebox run

# Or with proper XML parsing
curl -s "https://example.com/feed.xml" \
  | xq -r '.rss.channel.item[].link' \
  | archivebox crawl create \
  | archivebox run
```

### 9. Archive Audit with jq
```bash
# Count snapshots by status
archivebox snapshot list | jq -s 'group_by(.status) | map({status: .[0].status, count: length})'

# Find large archive results (over 50MB)
archivebox archiveresult list \
  | jq 'select(.output_size > 52428800) | {id, plugin, size_mb: (.output_size/1048576)}'

# Export summary of archive
archivebox snapshot list \
  | jq -s '{total: length, by_status: (group_by(.status) | map({(.[0].status): length}) | add)}'
```

### 10. Incremental Backup
```bash
# Archive URLs not already in archive
comm -23 \
  <(sort new_urls.txt) \
  <(archivebox snapshot list | jq -r '.url' | sort) \
  | archivebox crawl create \
  | archivebox run

# Re-archive anything older than 30 days
archivebox snapshot list \
  | jq "select(.created_at < \"$(date -d '30 days ago' --iso-8601)\")" \
  | archivebox archiveresult create \
  | archivebox run
```

### Composability Summary

| Pattern | Example |
|---------|---------|
| **Filter → Process** | `list --status=failed \| run` |
| **Transform → Archive** | `curl RSS \| jq \| crawl create \| run` |
| **Bulk Tag** | `list --url__icontains=X \| update --tag=Y` |
| **Selective Extract** | `snapshot list \| archiveresult create --plugin=pdf` |
| **Chain Depth** | `crawl create --depth=2 \| run` |
| **Export/Audit** | `list \| jq -s 'group_by(.status)'` |
| **Compose with Unix** | `\| jq \| grep \| sort \| uniq \| parallel` |

The key insight: **every intermediate step produces valid JSONL** that can be saved, filtered,
transformed, or resumed later. This makes archiving workflows debuggable, repeatable, and
composable with the entire Unix ecosystem.

---

## Code Reuse Findings

### Existing Model Methods (USE THESE)
- `Crawl.to_json()`, `Crawl.from_json()`, `Crawl.to_jsonl()`, `Crawl.from_jsonl()`
- `Snapshot.to_json()`, `Snapshot.from_json()`, `Snapshot.to_jsonl()`, `Snapshot.from_jsonl()`
- `Tag.to_json()`, `Tag.from_json()`, `Tag.to_jsonl()`, `Tag.from_jsonl()`

### Missing Model Methods (MUST IMPLEMENT)
- **`ArchiveResult.from_json()`** - Does not exist, must be added
- **`ArchiveResult.from_jsonl()`** - Does not exist, must be added

### Existing Utilities (USE THESE)
- `archivebox/misc/jsonl.py`: `read_stdin()`, `read_args_or_stdin()`, `write_record()`, `parse_line()`
- Type constants: `TYPE_CRAWL`, `TYPE_SNAPSHOT`, `TYPE_ARCHIVERESULT`, etc.

### Duplicated Code (EXTRACT)
- `apply_filters()` duplicated in 7 CLI files → extract to `archivebox/cli/cli_utils.py`

### Supervisord Config (UPDATE)
- `archivebox/workers/supervisord_util.py` line ~35: `"command": "archivebox manage orchestrator"` → `"command": "archivebox run"`

### Field Name Standardization (FIX)
- **Issue**: `Crawl.to_json()` outputs `tags_str`, but `Snapshot.to_json()` outputs `tags`
- **Fix**: Standardize all models to use `tags_str` in JSONL output (matches model property names)

---

## Implementation Order

### Phase 1: Model Prerequisites
1. **Implement `ArchiveResult.from_json()`** in `archivebox/core/models.py`
   - Pattern: Match `Snapshot.from_json()` and `Crawl.from_json()` style
   - Handle: ID lookup (update existing) or create new
   - Required fields: `snapshot_id`, `plugin`
   - Optional fields: `status`, `hook_name`, etc.

2. **Implement `ArchiveResult.from_jsonl()`** in `archivebox/core/models.py`
   - Filter records by `type='ArchiveResult'`
   - Call `from_json()` for each matching record

3. **Fix `Snapshot.to_json()` field name**
   - Change `'tags': self.tags_str()` → `'tags_str': self.tags_str()`
   - Update any code that depends on `tags` key in Snapshot JSONL

### Phase 2: Shared Utilities
4. **Extract `apply_filters()` to `archivebox/cli/cli_utils.py`**
   - Generic queryset filtering from CLI kwargs
   - Support `--id__in=[csv]`, `--url__icontains=str`, etc.
   - Remove duplicates from 7 CLI files

### Phase 3: Pass-Through Behavior (NEW FEATURE)
5. **Add pass-through to `archivebox crawl create`**
   - Output non-Crawl input records unchanged
   - Output created Crawl records

6. **Add pass-through to `archivebox snapshot create`**
   - Output non-Snapshot/non-Crawl input records unchanged
   - Process Crawl records → create Snapshots
   - Output both original Crawl and created Snapshots

7. **Add pass-through to `archivebox archiveresult create`**
   - Output non-Snapshot/non-ArchiveResult input records unchanged
   - Process Snapshot records → create ArchiveResults
   - Output both original Snapshots and created ArchiveResults

8. **Add create-or-update to `archivebox run`**
   - Records WITH id: lookup and queue existing
   - Records WITHOUT id: create via `Model.from_json()`, then queue
   - Pass-through output of all processed records

### Phase 4: Test Infrastructure
9. **Create `archivebox/tests/conftest.py`** with pytest-django
   - Use `pytest-django` for proper test database handling
   - Isolated DATA_DIR per test via `tmp_path` fixture
   - `run_archivebox_cmd()` helper for subprocess testing

### Phase 5: Unit Tests
10. **Create `archivebox/tests/test_cli_crawl.py`** - crawl create/list/pass-through tests
11. **Create `archivebox/tests/test_cli_snapshot.py`** - snapshot create/list/pass-through tests
12. **Create `archivebox/tests/test_cli_archiveresult.py`** - archiveresult create/list/pass-through tests
13. **Create `archivebox/tests/test_cli_run.py`** - run command create-or-update tests

### Phase 6: Integration & Config
14. **Extend `archivebox/cli/tests_piping.py`** - Add pass-through integration tests
15. **Update supervisord config** - `orchestrator` → `run`

---

## Future Work (Deferred)

### Commands to Defer
- `archivebox tag create|list|update|delete` - Already works, defer improvements
- `archivebox binary create|list|update|delete` - Lower priority
- `archivebox process list` - Lower priority
- `archivebox apikey create|list|update|delete` - Lower priority

### `archivebox add` Relationship
- **Current**: `archivebox add` is the primary user-facing command, stays as-is
- **Future**: Refactor `add` to internally use `crawl create | snapshot create | run` pipeline
- **Note**: This refactor is deferred; `add` continues to work independently for now

---

## Key Files

| File | Action | Phase |
|------|--------|-------|
| `archivebox/core/models.py` | Add `ArchiveResult.from_json()`, `from_jsonl()` | 1 |
| `archivebox/core/models.py` | Fix `Snapshot.to_json()` → `tags_str` | 1 |
| `archivebox/cli/cli_utils.py` | NEW - shared `apply_filters()` | 2 |
| `archivebox/cli/archivebox_crawl.py` | Add pass-through to create | 3 |
| `archivebox/cli/archivebox_snapshot.py` | Add pass-through to create | 3 |
| `archivebox/cli/archivebox_archiveresult.py` | Add pass-through to create | 3 |
| `archivebox/cli/archivebox_run.py` | Add create-or-update, pass-through | 3 |
| `archivebox/tests/conftest.py` | NEW - pytest fixtures | 4 |
| `archivebox/tests/test_cli_crawl.py` | NEW - crawl unit tests | 5 |
| `archivebox/tests/test_cli_snapshot.py` | NEW - snapshot unit tests | 5 |
| `archivebox/tests/test_cli_archiveresult.py` | NEW - archiveresult unit tests | 5 |
| `archivebox/tests/test_cli_run.py` | NEW - run unit tests | 5 |
| `archivebox/cli/tests_piping.py` | Extend with pass-through tests | 6 |
| `archivebox/workers/supervisord_util.py` | Update orchestrator→run | 6 |

---

## Implementation Details

### ArchiveResult.from_json() Design

```python
@staticmethod
def from_json(record: Dict[str, Any], overrides: Dict[str, Any] = None) -> 'ArchiveResult | None':
    """
    Create or update a single ArchiveResult from a JSON record dict.

    Args:
        record: Dict with 'snapshot_id' and 'plugin' (required for create),
                or 'id' (for update)
        overrides: Dict of field overrides

    Returns:
        ArchiveResult instance or None if invalid
    """
    from django.utils import timezone

    overrides = overrides or {}

    # If 'id' is provided, lookup and update existing
    result_id = record.get('id')
    if result_id:
        try:
            result = ArchiveResult.objects.get(id=result_id)
            # Update fields from record
            if record.get('status'):
                result.status = record['status']
                result.retry_at = timezone.now()
            result.save()
            return result
        except ArchiveResult.DoesNotExist:
            pass  # Fall through to create

    # Required fields for creation
    snapshot_id = record.get('snapshot_id')
    plugin = record.get('plugin')

    if not snapshot_id or not plugin:
        return None

    try:
        snapshot = Snapshot.objects.get(id=snapshot_id)
    except Snapshot.DoesNotExist:
        return None

    # Create or get existing result
    result, created = ArchiveResult.objects.get_or_create(
        snapshot=snapshot,
        plugin=plugin,
        defaults={
            'status': record.get('status', ArchiveResult.StatusChoices.QUEUED),
            'retry_at': timezone.now(),
            'hook_name': record.get('hook_name', ''),
            **overrides,
        }
    )

    # If not created, optionally reset for retry
    if not created and record.get('status'):
        result.status = record['status']
        result.retry_at = timezone.now()
        result.save()

    return result
```

### Pass-Through Pattern

All `create` commands follow this pattern:

```python
def create_X(args, ...):
    is_tty = sys.stdout.isatty()
    records = list(read_args_or_stdin(args))

    for record in records:
        record_type = record.get('type')

        # Pass-through: output records we don't handle
        if record_type not in HANDLED_TYPES:
            if not is_tty:
                write_record(record)
            continue

        # Handle our type: create via Model.from_json()
        obj = Model.from_json(record, overrides={...})

        # Output created record (hydrated with db id)
        if obj and not is_tty:
            write_record(obj.to_json())
```

### Pass-Through Semantics Example

```
Input:
  {"type": "Crawl", "id": "abc", "urls": "https://example.com", ...}
  {"type": "Tag", "name": "important"}

archivebox snapshot create output:
  {"type": "Crawl", "id": "abc", ...}           # pass-through (not our type)
  {"type": "Tag", "name": "important"}          # pass-through (not our type)
  {"type": "Snapshot", "id": "xyz", ...}        # created from Crawl URLs
```

### Create-or-Update Pattern for `archivebox run`

```python
def process_stdin_records() -> int:
    records = list(read_stdin())
    is_tty = sys.stdout.isatty()

    for record in records:
        record_type = record.get('type')
        record_id = record.get('id')

        # Create-or-update based on whether ID exists
        if record_type == TYPE_CRAWL:
            if record_id:
                try:
                    obj = Crawl.objects.get(id=record_id)
                except Crawl.DoesNotExist:
                    obj = Crawl.from_json(record)
            else:
                obj = Crawl.from_json(record)

            if obj:
                obj.retry_at = timezone.now()
                obj.save()
                if not is_tty:
                    write_record(obj.to_json())

        # Similar for Snapshot, ArchiveResult...
```

### Shared apply_filters() Design

Extract to `archivebox/cli/cli_utils.py`:

```python
"""Shared CLI utilities for ArchiveBox commands."""

from typing import Optional

def apply_filters(queryset, filter_kwargs: dict, limit: Optional[int] = None):
    """
    Apply Django-style filters from CLI kwargs to a QuerySet.

    Supports: --status=queued, --url__icontains=example, --id__in=uuid1,uuid2

    Args:
        queryset: Django QuerySet to filter
        filter_kwargs: Dict of filter key-value pairs from CLI
        limit: Optional limit on results

    Returns:
        Filtered QuerySet
    """
    filters = {}
    for key, value in filter_kwargs.items():
        if value is None or key in ('limit', 'offset'):
            continue
        # Handle CSV lists for __in filters
        if key.endswith('__in') and isinstance(value, str):
            value = [v.strip() for v in value.split(',')]
        filters[key] = value

    if filters:
        queryset = queryset.filter(**filters)
    if limit:
        queryset = queryset[:limit]

    return queryset
```

---

## conftest.py Design (pytest-django)

```python
"""archivebox/tests/conftest.py - Pytest fixtures for CLI tests."""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def isolated_data_dir(tmp_path, settings):
    """
    Create isolated DATA_DIR for each test.

    Uses tmp_path for isolation, configures Django settings.
    """
    data_dir = tmp_path / 'archivebox_data'
    data_dir.mkdir()

    # Set environment for subprocess calls
    os.environ['DATA_DIR'] = str(data_dir)

    # Update Django settings
    settings.DATA_DIR = data_dir

    yield data_dir

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def initialized_archive(isolated_data_dir):
    """
    Initialize ArchiveBox archive in isolated directory.

    Runs `archivebox init` to set up database and directories.
    """
    from archivebox.cli.archivebox_init import init
    init(setup=True, quick=True)
    return isolated_data_dir


@pytest.fixture
def cli_env(initialized_archive):
    """
    Environment dict for CLI subprocess calls.

    Includes DATA_DIR and disables slow extractors.
    """
    return {
        **os.environ,
        'DATA_DIR': str(initialized_archive),
        'USE_COLOR': 'False',
        'SHOW_PROGRESS': 'False',
        'SAVE_TITLE': 'True',
        'SAVE_FAVICON': 'False',
        'SAVE_WGET': 'False',
        'SAVE_WARC': 'False',
        'SAVE_PDF': 'False',
        'SAVE_SCREENSHOT': 'False',
        'SAVE_DOM': 'False',
        'SAVE_SINGLEFILE': 'False',
        'SAVE_READABILITY': 'False',
        'SAVE_MERCURY': 'False',
        'SAVE_GIT': 'False',
        'SAVE_YTDLP': 'False',
        'SAVE_HEADERS': 'False',
    }


# =============================================================================
# CLI Helpers
# =============================================================================

def run_archivebox_cmd(
    args: List[str],
    stdin: Optional[str] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Tuple[str, str, int]:
    """
    Run archivebox command, return (stdout, stderr, returncode).

    Args:
        args: Command arguments (e.g., ['crawl', 'create', 'https://example.com'])
        stdin: Optional string to pipe to stdin
        cwd: Working directory (defaults to DATA_DIR from env)
        env: Environment variables (defaults to os.environ with DATA_DIR)
        timeout: Command timeout in seconds

    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    cmd = [sys.executable, '-m', 'archivebox'] + args

    env = env or {**os.environ}
    cwd = cwd or Path(env.get('DATA_DIR', '.'))

    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )

    return result.stdout, result.stderr, result.returncode


# =============================================================================
# Output Assertions
# =============================================================================

def parse_jsonl_output(stdout: str) -> List[Dict[str, Any]]:
    """Parse JSONL output into list of dicts."""
    records = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if line and line.startswith('{'):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def assert_jsonl_contains_type(stdout: str, record_type: str, min_count: int = 1):
    """Assert output contains at least min_count records of type."""
    records = parse_jsonl_output(stdout)
    matching = [r for r in records if r.get('type') == record_type]
    assert len(matching) >= min_count, \
        f"Expected >= {min_count} {record_type}, got {len(matching)}"
    return matching


def assert_jsonl_pass_through(stdout: str, input_records: List[Dict[str, Any]]):
    """Assert that input records appear in output (pass-through behavior)."""
    output_records = parse_jsonl_output(stdout)
    output_ids = {r.get('id') for r in output_records if r.get('id')}

    for input_rec in input_records:
        input_id = input_rec.get('id')
        if input_id:
            assert input_id in output_ids, \
                f"Input record {input_id} not found in output (pass-through failed)"


def assert_record_has_fields(record: Dict[str, Any], required_fields: List[str]):
    """Assert record has all required fields with non-None values."""
    for field in required_fields:
        assert field in record, f"Record missing field: {field}"
        assert record[field] is not None, f"Record field is None: {field}"


# =============================================================================
# Database Assertions
# =============================================================================

def assert_db_count(model_class, filters: Dict[str, Any], expected: int):
    """Assert database count matches expected."""
    actual = model_class.objects.filter(**filters).count()
    assert actual == expected, \
        f"Expected {expected} {model_class.__name__}, got {actual}"


def assert_db_exists(model_class, **filters):
    """Assert at least one record exists matching filters."""
    assert model_class.objects.filter(**filters).exists(), \
        f"No {model_class.__name__} found matching {filters}"


# =============================================================================
# Test Data Factories
# =============================================================================

def create_test_url(domain: str = 'example.com', path: str = None) -> str:
    """Generate unique test URL."""
    import uuid
    path = path or uuid.uuid4().hex[:8]
    return f'https://{domain}/{path}'


def create_test_crawl_json(urls: List[str] = None, **kwargs) -> Dict[str, Any]:
    """Create Crawl JSONL record for testing."""
    from archivebox.misc.jsonl import TYPE_CRAWL

    urls = urls or [create_test_url()]
    return {
        'type': TYPE_CRAWL,
        'urls': '\n'.join(urls),
        'max_depth': kwargs.get('max_depth', 0),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('max_depth', 'tags_str', 'status')},
    }


def create_test_snapshot_json(url: str = None, **kwargs) -> Dict[str, Any]:
    """Create Snapshot JSONL record for testing."""
    from archivebox.misc.jsonl import TYPE_SNAPSHOT

    return {
        'type': TYPE_SNAPSHOT,
        'url': url or create_test_url(),
        'tags_str': kwargs.get('tags_str', ''),
        'status': kwargs.get('status', 'queued'),
        **{k: v for k, v in kwargs.items() if k not in ('tags_str', 'status')},
    }
```

---

## Test Rules

- **NO SKIPPING** - Every test runs
- **NO MOCKING** - Real subprocess calls, real database
- **NO DISABLING** - Failing tests identify real problems
- **MINIMAL CODE** - Import helpers from conftest.py
- **ISOLATED** - Each test gets its own DATA_DIR via `tmp_path`

---

## Task Checklist

### Phase 1: Model Prerequisites
- [ ] Implement `ArchiveResult.from_json()` in `archivebox/core/models.py`
- [ ] Implement `ArchiveResult.from_jsonl()` in `archivebox/core/models.py`
- [ ] Fix `Snapshot.to_json()` to use `tags_str` instead of `tags`

### Phase 2: Shared Utilities
- [ ] Create `archivebox/cli/cli_utils.py` with shared `apply_filters()`
- [ ] Update 7 CLI files to import from `cli_utils.py`

### Phase 3: Pass-Through Behavior
- [ ] Add pass-through to `archivebox_crawl.py` create
- [ ] Add pass-through to `archivebox_snapshot.py` create
- [ ] Add pass-through to `archivebox_archiveresult.py` create
- [ ] Add create-or-update to `archivebox_run.py`
- [ ] Add pass-through output to `archivebox_run.py`

### Phase 4: Test Infrastructure
- [ ] Create `archivebox/tests/conftest.py` with pytest-django fixtures

### Phase 5: Unit Tests
- [ ] Create `archivebox/tests/test_cli_crawl.py`
- [ ] Create `archivebox/tests/test_cli_snapshot.py`
- [ ] Create `archivebox/tests/test_cli_archiveresult.py`
- [ ] Create `archivebox/tests/test_cli_run.py`

### Phase 6: Integration & Config
- [ ] Extend `archivebox/cli/tests_piping.py` with pass-through tests
- [ ] Update `archivebox/workers/supervisord_util.py`: orchestrator→run
