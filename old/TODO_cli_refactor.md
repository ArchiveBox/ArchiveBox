# ArchiveBox CLI Refactor TODO

## Design Decisions

1. **Keep `archivebox add`** as high-level convenience command
2. **Unified `archivebox run`** for processing (replaces per-model `run` and `orchestrator`)
3. **Expose all models** including binary, process, machine
4. **Clean break** from old command structure (no backward compatibility aliases)

## Final Architecture

```
archivebox <model> <action> [args...] [--filters]
archivebox run [stdin JSONL]
```

### Actions (4 per model):
- `create` - Create records (from args, stdin, or JSONL), dedupes by indexed fields
- `list` - Query records (with filters, returns JSONL)
- `update` - Modify records (from stdin JSONL, PATCH semantics)
- `delete` - Remove records (from stdin JSONL, requires --yes)

### Unified Run Command:
- `archivebox run` - Process queued work
  - With stdin JSONL: Process piped records, exit when complete
  - Without stdin (TTY): Run orchestrator in foreground until killed

### Models (7 total):
- `crawl` - Crawl jobs
- `snapshot` - Individual archived pages
- `archiveresult` - Plugin extraction results
- `tag` - Tags/labels
- `binary` - Detected binaries (chrome, wget, etc.)
- `process` - Process execution records (read-only)
- `machine` - Machine/host records (read-only)

---

## Implementation Checklist

### Phase 1: Unified Run Command
- [x] Create `archivebox/cli/archivebox_run.py` - unified processing command

### Phase 2: Core Model Commands
- [x] Refactor `archivebox/cli/archivebox_snapshot.py` to Click group with create|list|update|delete
- [x] Refactor `archivebox/cli/archivebox_crawl.py` to Click group with create|list|update|delete
- [x] Create `archivebox/cli/archivebox_archiveresult.py` with create|list|update|delete
- [x] Create `archivebox/cli/archivebox_tag.py` with create|list|update|delete

### Phase 3: System Model Commands
- [x] Create `archivebox/cli/archivebox_binary.py` with create|list|update|delete
- [x] Create `archivebox/cli/archivebox_process.py` with list only (read-only)
- [x] Create `archivebox/cli/archivebox_machine.py` with list only (read-only)

### Phase 4: Registry & Cleanup
- [x] Update `archivebox/cli/__init__.py` command registry
- [x] Delete `archivebox/cli/archivebox_extract.py`
- [x] Delete `archivebox/cli/archivebox_remove.py`
- [x] Delete `archivebox/cli/archivebox_search.py`
- [x] Delete `archivebox/cli/archivebox_orchestrator.py`
- [x] Update `archivebox/cli/archivebox_add.py` internals (no changes needed - uses models directly)
- [x] Update `archivebox/cli/tests_piping.py`

### Phase 5: Tests for New Commands
- [ ] Add tests for `archivebox run` command
- [ ] Add tests for `archivebox crawl create|list|update|delete`
- [ ] Add tests for `archivebox snapshot create|list|update|delete`
- [ ] Add tests for `archivebox archiveresult create|list|update|delete`
- [ ] Add tests for `archivebox tag create|list|update|delete`
- [ ] Add tests for `archivebox binary create|list|update|delete`
- [ ] Add tests for `archivebox process list`
- [ ] Add tests for `archivebox machine list`

---

## Usage Examples

### Basic CRUD
```bash
# Create
archivebox crawl create https://example.com https://foo.com --depth=1
archivebox snapshot create https://example.com --tag=news

# List with filters
archivebox crawl list --status=queued
archivebox snapshot list --url__icontains=example.com
archivebox archiveresult list --status=failed --plugin=screenshot

# Update (reads JSONL from stdin, applies changes)
archivebox snapshot list --tag=old | archivebox snapshot update --tag=new

# Delete (requires --yes)
archivebox crawl list --url__icontains=example.com | archivebox crawl delete --yes
```

### Unified Run Command
```bash
# Run orchestrator in foreground (replaces `archivebox orchestrator`)
archivebox run

# Process specific records (pipe any JSONL type, exits when done)
archivebox snapshot list --status=queued | archivebox run
archivebox archiveresult list --status=failed | archivebox run
archivebox crawl list --status=queued | archivebox run

# Mixed types work too - run handles any JSONL
cat mixed_records.jsonl | archivebox run
```

### Composed Workflows
```bash
# Full pipeline (replaces old `archivebox add`)
archivebox crawl create https://example.com --status=queued \
  | archivebox snapshot create --status=queued \
  | archivebox archiveresult create --status=queued \
  | archivebox run

# Re-run failed extractions
archivebox archiveresult list --status=failed | archivebox run

# Delete all snapshots for a domain
archivebox snapshot list --url__icontains=spam.com | archivebox snapshot delete --yes
```

### Keep `archivebox add` as convenience
```bash
# This remains the simple user-friendly interface:
archivebox add https://example.com --depth=1 --tag=news

# Internally equivalent to the composed pipeline above
```
