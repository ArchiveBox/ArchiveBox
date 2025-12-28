# TODO: Rename Extractor to Plugin - Implementation Progress

**Status**: 🟡 In Progress (2/13 phases complete)
**Started**: 2025-12-28
**Estimated Files to Update**: ~150+ files

---

## Progress Overview

### ✅ Completed Phases (2/13)

- [x] **Phase 1**: Database Migration - Created migration 0033
- [x] **Phase 2**: Core Model Updates - Updated ArchiveResult, ArchiveResultManager, Snapshot models

### 🟡 In Progress (1/13)

- [ ] **Phase 3**: Hook Execution System (hooks.py - all function renames)

### ⏳ Pending Phases (10/13)

- [ ] **Phase 4**: JSONL Import/Export (misc/jsonl.py)
- [ ] **Phase 5**: CLI Commands (archivebox_extract, archivebox_add, archivebox_update)
- [ ] **Phase 6**: API Endpoints (v1_core.py, v1_cli.py)
- [ ] **Phase 7**: Admin Interface (admin_archiveresults.py, forms.py)
- [ ] **Phase 8**: Views and Templates (views.py, templatetags, progress_monitor.html)
- [ ] **Phase 9**: Worker System (workers/worker.py)
- [ ] **Phase 10**: State Machine (statemachines.py)
- [ ] **Phase 11**: Tests (test_migrations_helpers.py, test_recursive_crawl.py, etc.)
- [ ] **Phase 12**: Terminology Standardization (via_extractor→plugin, comments, docstrings)
- [ ] **Phase 13**: Run migrations and verify all tests pass

---

## What's Been Completed So Far

### Phase 1: Database Migration ✅

**File Created**: `archivebox/core/migrations/0033_rename_extractor_add_hook_name.py`

Changes:
- Used `migrations.RenameField()` to rename `extractor` → `plugin`
- Added `hook_name` field (CharField, max_length=255, indexed, default='')
- Preserves all existing data, indexes, and constraints

### Phase 2: Core Models ✅

**File Updated**: `archivebox/core/models.py`

#### ArchiveResultManager
- Updated `indexable()` method to use `plugin__in` and `plugin=method`
- Changed reference from `ARCHIVE_METHODS_INDEXING_PRECEDENCE` to `EXTRACTOR_INDEXING_PRECEDENCE`

#### ArchiveResult Model
**Field Changes**:
- Renamed field: `extractor` → `plugin`
- Added field: `hook_name` (stores full filename like `on_Snapshot__50_wget.py`)
- Updated comments to reference "plugin" instead of "extractor"

**Method Updates**:
- `get_extractor_choices()` → `get_plugin_choices()`
- `__str__()`: Now uses `self.plugin`
- `save()`: Logs `plugin` instead of `extractor`
- `get_absolute_url()`: Uses `self.plugin`
- `extractor_module` property → `plugin_module` property
- `output_exists()`: Checks `self.plugin` directory
- `embed_path()`: Uses `self.plugin` for paths
- `create_output_dir()`: Creates `self.plugin` directory
- `output_dir_name`: Returns `self.plugin`
- `run()`: All references to extractor → plugin (including extractor_dir → plugin_dir)
- `update_from_output()`: All references updated to plugin/plugin_dir
- `_update_snapshot_title()`: Parameter renamed to `plugin_dir`
- `trigger_search_indexing()`: Passes `plugin=self.plugin`
- `output_dir` property: Returns plugin directory
- `is_background_hook()`: Uses `plugin_dir`

#### Snapshot Model
**Method Updates**:
- `create_pending_archiveresults()`: Uses `get_enabled_plugins()`, filters by `plugin=plugin`
- `result_icons` (calc_icons): Maps by `r.plugin`, calls `get_plugin_name()` and `get_plugin_icon()`
- `_merge_archive_results_from_index()`: Maps by `(ar.plugin, ar.start_ts)`, supports both 'extractor' and 'plugin' keys for backwards compat
- `_create_archive_result_if_missing()`: Supports both 'extractor' and 'plugin' keys, creates with `plugin=plugin`
- `write_index_json()`: Writes `'plugin': ar.plugin` in archive_results
- `canonical_outputs()`: Updates `find_best_output_in_dir()` to use `plugin_name`, accesses `result.plugin`, creates keys like `{result.plugin}_path`
- `latest_outputs()`: Uses `get_plugins()`, filters by `plugin=plugin`
- `retry_failed_archiveresults()`: Updated docstring to reference "plugins" instead of "extractors"

**Total Lines Changed in models.py**: ~50+ locations

---

## Full Implementation Plan

# ArchiveResult Model Refactoring Plan: Rename Extractor to Plugin + Add Hook Name Field

## Overview
Refactor the ArchiveResult model and standardize terminology across the codebase:
1. Rename the `extractor` field to `plugin` in ArchiveResult model
2. Add a new `hook_name` field to store the specific hook filename that executed
3. Update all related code paths (CLI, API, admin, views, hooks, JSONL, etc.)
4. Standardize CLI flags from `--extract/--extractors` to `--plugins`
5. **Standardize terminology throughout codebase**:
   - "parsers" → "parser plugins"
   - "extractors" → "extractor plugins"
   - "parser extractors" → "parser plugins"
   - "archive methods" → "extractor plugins"
   - Document apt/brew/npm/pip as "package manager plugins" in comments

## Current State Analysis

### ArchiveResult Model (archivebox/core/models.py:1679-1750)
```python
class ArchiveResult(ModelWithOutputDir, ...):
    extractor = models.CharField(max_length=32, db_index=True)  # e.g., "screenshot", "wget"
    # New fields from migration 0029:
    output_str, output_json, output_files, output_size, output_mimetypes
    binary = ForeignKey('machine.Binary', ...)
    # No hook_name field yet
```

### Hook Execution Flow
1. `ArchiveResult.run()` discovers hooks for the plugin (e.g., `wget/on_Snapshot__50_wget.py`)
2. `run_hook()` executes each hook script, captures output as HookResult
3. `update_from_output()` parses JSONL and updates ArchiveResult fields
4. Currently NO tracking of which specific hook file executed

### Field Usage Across Codebase
**extractor field** is used in ~100 locations:
- **Model**: ArchiveResult.extractor field definition, __str__, manager queries
- **CLI**: archivebox_extract.py (--plugin flag), archivebox_add.py, tests
- **API**: v1_core.py (extractor filter), v1_cli.py (extract/extractors args)
- **Admin**: admin_archiveresults.py (list filter, display)
- **Views**: core/views.py (archiveresult_objects dict by extractor)
- **Template Tags**: core_tags.py (extractor_icon, extractor_thumbnail, extractor_embed)
- **Hooks**: hooks.py (get_extractors, get_extractor_name, run_hook output parsing)
- **JSONL**: misc/jsonl.py (archiveresult_to_jsonl serializes extractor)
- **Worker**: workers/worker.py (ArchiveResultWorker filters by extractor)
- **Statemachine**: statemachines.py (logs extractor in state transitions)

---

## Implementation Plan

### Phase 1: Database Migration (archivebox/core/migrations/) ✅ COMPLETE

**Create migration 0033_rename_extractor_add_hook_name.py**:
1. Rename field: `extractor` → `plugin` (preserve index, constraints)
2. Add field: `hook_name` = CharField(max_length=255, blank=True, default='', db_index=True)
   - **Stores full hook filename**: `on_Snapshot__50_wget.py`, `on_Crawl__10_chrome_session.js`, etc.
   - Empty string for existing records (data migration sets all to '')
3. Update any indexes or constraints that reference extractor

**Decision**: Full filename chosen for explicitness and easy grep-ability

**Critical Files to Update**:
- ✅ ArchiveResult model field definitions
- ✅ Migration dependencies (latest: 0032)

---

### Phase 2: Core Model Updates (archivebox/core/models.py) ✅ COMPLETE

**ArchiveResult Model** (lines 1679-1820):
- ✅ Rename field: `extractor` → `plugin`
- ✅ Add field: `hook_name = models.CharField(...)`
- ✅ Update __str__: `f'...-> {self.plugin}'`
- ✅ Update absolute_url: Use plugin instead of extractor
- ✅ Update embed_path: Use plugin directory name

**ArchiveResultManager** (lines 1669-1677):
- ✅ Update indexable(): `filter(plugin__in=INDEXABLE_METHODS, ...)`
- ✅ Update precedence: `When(plugin=method, ...)`

**Snapshot Model** (lines 1000-1600):
- ✅ Update canonical_outputs: Access by plugin name
- ✅ Update create_pending_archiveresults: Use plugin parameter
- ✅ All queryset filters: `archiveresult_set.filter(plugin=...)`

---

### Phase 3: Hook Execution System (archivebox/hooks.py) 🟡 IN PROGRESS

**Function Renames**:
- [ ] `get_extractors()` → `get_plugins()` (lines 479-504)
- [ ] `get_parser_extractors()` → `get_parser_plugins()` (lines 507-514)
- [ ] `get_extractor_name()` → `get_plugin_name()` (lines 517-530)
- [ ] `is_parser_extractor()` → `is_parser_plugin()` (lines 533-536)
- [ ] `get_enabled_extractors()` → `get_enabled_plugins()` (lines 553-566)
- [ ] `get_extractor_template()` → `get_plugin_template()` (line 1048)
- [ ] `get_extractor_icon()` → `get_plugin_icon()` (line 1068)
- [ ] `get_all_extractor_icons()` → `get_all_plugin_icons()` (line 1092)

**Update HookResult TypedDict** (lines 63-73):
- [ ] Add field: `hook_name: str` to store hook filename
- [ ] Add field: `plugin: str` (if not already present)

**Update run_hook()** (lines 141-389):
- [ ] **Add hook_name parameter**: Pass hook filename to be stored in result
- [ ] Update HookResult to include hook_name field
- [ ] Update JSONL record output: Add `hook_name` key

**Update ArchiveResult.run()** (lines 1838-1914):
- [ ] When calling run_hook, pass the hook filename
- [ ] Store hook_name in ArchiveResult before/after execution

**Update ArchiveResult.update_from_output()** (lines 1916-2073):
- [ ] Parse hook_name from JSONL output
- [ ] Store in self.hook_name field
- [ ] If not present in JSONL, infer from directory/filename

**Constants to Rename**:
- [ ] `ARCHIVE_METHODS_INDEXING_PRECEDENCE` → `EXTRACTOR_INDEXING_PRECEDENCE`

**Comments/Docstrings**: Update all function docstrings to use "plugin" terminology

---

### Phase 4: JSONL Import/Export (archivebox/misc/jsonl.py)

**Update archiveresult_to_jsonl()** (lines 173-200):
- [ ] Change key: `'extractor': result.extractor` → `'plugin': result.plugin`
- [ ] Add key: `'hook_name': result.hook_name`

**Update JSONL parsing**:
- [ ] **Accept both 'extractor' (legacy) and 'plugin' (new) keys when importing**
- [ ] Always write 'plugin' key in new exports (never 'extractor')
- [ ] Parse and store hook_name if present (backwards compat: empty if missing)

**Decision**: Support both keys on import for smooth migration, always export new format

---

### Phase 5: CLI Commands (archivebox/cli/)

**archivebox_extract.py** (lines 1-230):
- [ ] Rename flag: `--plugin` stays (already correct!)
- [ ] Update internal references: extractor → plugin
- [ ] Update filter: `results.filter(plugin=plugin)`
- [ ] Update display: `result.plugin`

**archivebox_add.py**:
- [ ] Rename config key: `'EXTRACTORS': plugins` → `'PLUGINS': plugins` (if not already)

**archivebox_update.py**:
- [ ] Standardize to `--plugins` flag (currently may be --extractors or --extract)

**tests/test_oneshot.py**:
- [ ] Update flag: `--extract=...` → `--plugins=...`

---

### Phase 6: API Endpoints (archivebox/api/)

**v1_core.py** (ArchiveResult API):
- [ ] Update schema field: `extractor: str` → `plugin: str`
- [ ] Update schema field: Add `hook_name: str = ''`
- [ ] Update FilterSchema: `q=[..., 'plugin', ...]`
- [ ] Update extractor filter: `plugin: Optional[str] = Field(None, q='plugin__icontains')`

**v1_cli.py** (CLI API):
- [ ] Rename AddCommandSchema field: `extract: str` → `plugins: str`
- [ ] Rename UpdateCommandSchema field: `extractors: str` → `plugins: str`
- [ ] Update endpoint mapping: `args.plugins` → `plugins` parameter

---

### Phase 7: Admin Interface (archivebox/core/)

**admin_archiveresults.py**:
- [ ] Update all references: extractor → plugin
- [ ] Update list_filter: `'plugin'` instead of `'extractor'`
- [ ] Update ordering: `order_by('plugin')`
- [ ] Update get_plugin_icon: (rename from get_extractor_icon if exists)

**admin_snapshots.py**:
- [ ] Update any commented TODOs referencing extractor

**forms.py**:
- [ ] Rename function: `get_archive_methods()` → `get_plugin_choices()`
- [ ] Update form field: `archive_methods` → `plugins`

---

### Phase 8: Views and Templates (archivebox/core/)

**views.py**:
- [ ] Update dict building: `archiveresult_objects[result.plugin] = result`
- [ ] Update all extractor references to plugin

**templatetags/core_tags.py**:
- [ ] **Rename template tags (BREAKING CHANGE)**:
  - `extractor_icon()` → `plugin_icon()`
  - `extractor_thumbnail()` → `plugin_thumbnail()`
  - `extractor_embed()` → `plugin_embed()`
- [ ] Update internal: `result.extractor` → `result.plugin`

**Update HTML templates** (if any directly reference extractor):
- [ ] Search for `{{ result.extractor }}` and similar
- [ ] Update to `{{ result.plugin }}`
- [ ] Update template tag calls
- [ ] **CRITICAL**: Update JavaScript in `templates/admin/progress_monitor.html`:
  - Lines 491, 505: Change `extractor.extractor` and `a.extractor` to use `plugin` field

---

### Phase 9: Worker System (archivebox/workers/worker.py)

**ArchiveResultWorker**:
- [ ] Rename parameter: `extractor` → `plugin` (lines 348, 350)
- [ ] Update filter: `qs.filter(plugin=self.plugin)`
- [ ] Update subprocess passing: Use plugin parameter

---

### Phase 10: State Machine (archivebox/core/statemachines.py)

**ArchiveResultMachine**:
- [ ] Update logging: Use `self.archiveresult.plugin` instead of extractor
- [ ] Update any state metadata that includes extractor field

---

### Phase 11: Tests and Fixtures

**Update test files**:
- [ ] tests/test_migrations_*.py: Update expected field names in schema definitions
- [ ] tests/test_hooks.py: Update assertions for plugin/hook_name fields
- [ ] archivebox/tests/test_migrations_helpers.py: Update schema SQL (lines 161, 382, 468)
- [ ] tests/test_recursive_crawl.py: Update SQL query `WHERE extractor = '60_parse_html_urls'` (line 163)
- [ ] archivebox/cli/tests_piping.py: Update test function names and assertions
- [ ] Any fixtures that create ArchiveResults: Use plugin parameter
- [ ] Any mock objects that set `.extractor` attribute: Change to `.plugin`

---

### Phase 12: Terminology Standardization (NEW)

This phase standardizes terminology throughout the codebase to use consistent "plugin" nomenclature.

**via_extractor → plugin Rename (14 files)**:
- [ ] Rename metadata field `via_extractor` to just `plugin`
- [ ] Files affected:
  - archivebox/hooks.py - Set plugin in run_hook() output
  - archivebox/crawls/models.py - If via_extractor field exists
  - archivebox/cli/archivebox_crawl.py - References to via_extractor
  - All parser plugins that set via_extractor in output
  - Test files with via_extractor assertions
- [ ] Update all JSONL output from parser plugins to use "plugin" key

**Logging Functions (archivebox/misc/logging_util.py)**:
- [ ] `log_archive_method_started()` → `log_extractor_started()` (line 326)
- [ ] `log_archive_method_finished()` → `log_extractor_finished()` (line 330)

**Form Functions (archivebox/core/forms.py)**:
- [ ] `get_archive_methods()` → `get_plugin_choices()` (line 15)
- [ ] Form field `archive_methods` → `plugins` (line 24, 29)
- [ ] Update form validation and view usage

**Comments and Docstrings (81 files with "extractor" references)**:
- [ ] Update comments to say "extractor plugin" instead of just "extractor"
- [ ] Update comments to say "parser plugin" instead of "parser extractor"
- [ ] All plugin files: Update docstrings to use "extractor plugin" terminology

**Package Manager Plugin Documentation**:
- [ ] Update comments in package manager hook files to say "package manager plugin":
  - archivebox/plugins/apt/on_Binary__install_using_apt_provider.py
  - archivebox/plugins/brew/on_Binary__install_using_brew_provider.py
  - archivebox/plugins/npm/on_Binary__install_using_npm_provider.py
  - archivebox/plugins/pip/on_Binary__install_using_pip_provider.py
  - archivebox/plugins/env/on_Binary__install_using_env_provider.py
  - archivebox/plugins/custom/on_Binary__install_using_custom_bash.py

**String Literals in Error Messages**:
- [ ] Search for error messages containing "extractor" and update to "plugin" or "extractor plugin"
- [ ] Search for error messages containing "parser" and update to "parser plugin" where appropriate

---

## Critical Files Summary

### Must Update (Core):
1. ✅ `archivebox/core/models.py` - ArchiveResult, ArchiveResultManager, Snapshot
2. ✅ `archivebox/core/migrations/0033_*.py` - New migration
3. ⏳ `archivebox/hooks.py` - All hook execution and discovery functions
4. ⏳ `archivebox/misc/jsonl.py` - Serialization/deserialization

### Must Update (CLI):
5. ⏳ `archivebox/cli/archivebox_extract.py`
6. ⏳ `archivebox/cli/archivebox_add.py`
7. ⏳ `archivebox/cli/archivebox_update.py`

### Must Update (API):
8. ⏳ `archivebox/api/v1_core.py`
9. ⏳ `archivebox/api/v1_cli.py`

### Must Update (Admin/Views):
10. ⏳ `archivebox/core/admin_archiveresults.py`
11. ⏳ `archivebox/core/views.py`
12. ⏳ `archivebox/core/templatetags/core_tags.py`

### Must Update (Workers/State):
13. ⏳ `archivebox/workers/worker.py`
14. ⏳ `archivebox/core/statemachines.py`

### Must Update (Tests):
15. ⏳ `tests/test_oneshot.py`
16. ⏳ `archivebox/tests/test_hooks.py`
17. ⏳ `archivebox/tests/test_migrations_helpers.py` - Schema SQL definitions
18. ⏳ `tests/test_recursive_crawl.py` - SQL queries with field names
19. ⏳ `archivebox/cli/tests_piping.py` - Test function docstrings

### Must Update (Terminology - Phase 12):
20. ⏳ `archivebox/misc/logging_util.py` - Rename logging functions
21. ⏳ `archivebox/core/forms.py` - Rename form helper and field
22. ⏳ `archivebox/templates/admin/progress_monitor.html` - JavaScript field refs
23. ⏳ All 81 plugin files - Update docstrings and comments
24. ⏳ 28 files with parser terminology - Update comments consistently

---

## Migration Strategy

### Data Migration for Existing Records:
```python
def forwards(apps, schema_editor):
    ArchiveResult = apps.get_model('core', 'ArchiveResult')
    # All existing records get empty hook_name
    ArchiveResult.objects.all().update(hook_name='')
```

### Backwards Compatibility:
**BREAKING CHANGES** (per user requirements - no backwards compat):
- CLI flags: Hard cutover to `--plugins` (no aliases)
- API fields: `extractor` removed, `plugin` required
- Template tags: All renamed to `plugin_*`

**PARTIAL COMPAT** (for migration):
- JSONL: Write 'plugin', but **accept both 'extractor' and 'plugin' on import**

---

## Testing Checklist

- [ ] Migration 0033 runs successfully on test database
- [ ] All migrations tests pass (test_migrations_*.py)
- [ ] All hook tests pass (test_hooks.py)
- [ ] CLI commands work with --plugins flag
- [ ] API endpoints return plugin/hook_name fields correctly
- [ ] Admin interface displays plugin correctly
- [ ] Admin progress monitor JavaScript works (no console errors)
- [ ] JSONL export includes both plugin and hook_name
- [ ] JSONL import accepts both 'extractor' and 'plugin' keys
- [ ] Hook execution populates hook_name field
- [ ] Worker filtering by plugin works
- [ ] Template tags render with new names (plugin_icon, etc.)
- [ ] All renamed functions work correctly
- [ ] SQL queries in tests use correct field names
- [ ] Terminology is consistent across codebase

---

## Critical Issues to Address

### 1. via_extractor Field (DECISION: RENAME)
- Currently used in 14 files for tracking which parser plugin discovered a URL
- **Decision**: Rename `via_extractor` → `plugin` (not via_plugin, just "plugin")
- **Impact**: Crawler and parser plugin code - 14 files to update
- Files affected:
  - archivebox/hooks.py
  - archivebox/crawls/models.py
  - archivebox/cli/archivebox_crawl.py
  - All parser plugins (parse_html_urls, parse_rss_urls, parse_jsonl_urls, etc.)
  - Tests: tests_piping.py, test_parse_rss_urls_comprehensive.py
- This creates consistent naming where "plugin" is used for both:
  - ArchiveResult.plugin (which extractor plugin ran)
  - URL discovery metadata "plugin" (which parser plugin discovered this URL)

### 2. Field Size Constraint
- Current: `extractor = CharField(max_length=32)`
- **Decision**: Keep max_length=32 when renaming to plugin
- No size increase needed

### 3. Migration Implementation
- Use `migrations.RenameField('ArchiveResult', 'extractor', 'plugin')` for clean migration
- Preserves data, indexes, and constraints automatically
- Add hook_name field in same migration

---

## Rollout Notes

**Breaking Changes**:
1. CLI: `--extract`, `--extractors` → `--plugins` (no aliases)
2. API: `extractor` field → `plugin` field (no backwards compat)
3. Template tags: `extractor_*` → `plugin_*` (users must update custom templates)
4. Python API: All function names with "extractor" → "plugin" (import changes needed)
5. Form fields: `archive_methods` → `plugins`
6. **via_extractor → plugin** (URL discovery metadata field)

**Migration Required**: Yes - all instances must run migrations before upgrading

**Estimated Impact**: ~150+ files will need updates across the entire codebase
- 81 files: extractor terminology
- 28 files: parser terminology
- 10 files: archive_method legacy terminology
- Plus templates, JavaScript, tests, etc.

---

## Next Steps

1. **Continue with Phase 3**: Update hooks.py with all function renames and hook_name tracking
2. **Then Phase 4**: Update JSONL import/export with backwards compatibility
3. **Then Phases 5-12**: Systematically update all remaining files
4. **Finally Phase 13**: Run full test suite and verify everything works

**Note**: Migration can be tested immediately - the migration file is ready to run!
