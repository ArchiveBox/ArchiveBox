# ArchiveBox TODOs

This directory contains detailed design documentation for major ArchiveBox systems.

## Active Design Documents

### [Lazy Filesystem Migration System](./TODO_fs_migrations.md)
**Problem**: `archivebox init` on 1TB+ collections takes hours/days scanning and migrating everything upfront.

**Solution**: O(1) init + lazy migration on save() + background worker + single-pass streaming update.

**Key Features**:
- O(1) init regardless of collection size
- Lazy migration happens automatically on `Snapshot.save()`
- Single streaming O(n) pass for `archivebox update`
- Atomic cp + verify + rm (safe to interrupt)
- Intelligent merging of index.json ↔ DB data
- Migration from flat structure to organized extractor subdirectories
- Backwards-compatible symlinks

**Status**: Design complete, ready for implementation

---

### [Hook Architecture & Background Hooks](./TODO_hook_architecture.md)
**Problem**: Need unified hook system for all models + support for long-running background extractors.

**Solution**: JSONL-based hook system with background hook support via `.bg.` suffix.

**Key Features**:
- Unified `Model.run()` pattern for Crawl, Dependency, Snapshot, ArchiveResult
- Hooks emit JSONL: `{type: 'ModelName', ...}`
- Generic `run_hook()` parser (doesn't know about specific models)
- Background hooks run concurrently without blocking
- Split `output` into `output_str` (human) and `output_json` (structured)
- New fields: `output_files`, `output_size`, `output_mimetypes`

**Status**: Phases 1-3 in progress, Phases 4-7 planned

---

## Implementation Order

1. **Filesystem Migration** (TODO_fs_migrations.md)
   - Database migration for `fs_version` field
   - `Snapshot.save()` with migration chain
   - Migration methods: `_migrate_fs_from_0_7_0_to_0_8_0()`, `_migrate_fs_from_0_8_0_to_0_9_0()`
   - `Snapshot.output_dir` property that derives path from `fs_version`
   - Simplify `archivebox init` to O(1)
   - Single-pass streaming `archivebox update`
   - Intelligent `reconcile_index_json()` merging
   - Runtime assertions and `archivebox doctor` checks

2. **Hook Architecture** (TODO_hook_architecture.md)
   - Phase 1: Database migration for new ArchiveResult fields
   - Phase 2: Update hooks to emit clean JSONL
   - Phase 3: Generic `run_hook()` implementation
   - Phase 4: Plugin audit and standardization
   - Phase 5: Update `run_hook()` for background support
   - Phase 6: Update `ArchiveResult.run()`
   - Phase 7: Background hook finalization

---

## Design Principles

Both systems follow these principles:

✅ **Never load all snapshots into memory** - Use `.iterator()` everywhere
✅ **Atomic operations** - Transactions protect DB, idempotent copies protect FS
✅ **Resumable** - Safe to kill and restart anytime
✅ **Correct by default** - Runtime assertions catch migration issues
✅ **Simple > Complex** - Avoid over-engineering, keep it predictable

---

## Related Files

- `CLAUDE.md` - Development guide and test suite documentation
- `.claude/CLAUDE.md` - User's global instructions (git workflow, DB connections)
