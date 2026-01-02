# TODO: Fix Migration Path for v0.7.2/v0.8.6rc0 → v0.9.0

## Critical Issue

The migrations currently **LOSE DATA** during the v0.7.2 → v0.9.0 upgrade:
- `extractor` field data is not being copied to `plugin` field
- `output` field data is not being copied to `output_str` field
- Timestamp fields (`added`, `updated`) may not be properly transformed
- Tag UUID → INTEGER conversion may lose FK relationships

## Test Database Locations

Sample databases for testing are available at:
```
/Users/squash/Local/Code/archiveboxes/archivebox-migration-path/archivebox-v0.7.2/data/index.sqlite3
/Users/squash/Local/Code/archiveboxes/archivebox-migration-path/archivebox-v0.8.6rc0/data/index.sqlite3
```

Schema comparison reports:
```
/tmp/schema_comparison_report.md
/tmp/table_presence_matrix.md
```

## How to Test Migrations

### 1. Fresh Install Test
```bash
rm -rf /tmp/test_fresh && mkdir -p /tmp/test_fresh
DATA_DIR=/tmp/test_fresh python -m archivebox init
DATA_DIR=/tmp/test_fresh python -m archivebox status
```

### 2. v0.7.2 Migration Test
```bash
rm -rf /tmp/test_v072 && mkdir -p /tmp/test_v072
cp /Users/squash/Local/Code/archiveboxes/archivebox-migration-path/archivebox-v0.7.2/data/index.sqlite3 /tmp/test_v072/
DATA_DIR=/tmp/test_v072 python -m archivebox init
DATA_DIR=/tmp/test_v072 python -m archivebox status
```

### 3. v0.8.6rc0 Migration Test
```bash
rm -rf /tmp/test_v086 && mkdir -p /tmp/test_v086
cp /Users/squash/Local/Code/archiveboxes/archivebox-migration-path/archivebox-v0.8.6rc0/data/index.sqlite3 /tmp/test_v086/
DATA_DIR=/tmp/test_v086 python -m archivebox init
DATA_DIR=/tmp/test_v086 python -m archivebox status
```

### 4. Verify Data Integrity

After each test, compare original vs migrated data:

```bash
# Check ArchiveResult data preservation
echo "=== ORIGINAL ==="
sqlite3 /path/to/original.db "SELECT id, extractor, output, status FROM core_archiveresult LIMIT 5;"

echo "=== MIGRATED ==="
sqlite3 /tmp/test_vXXX/index.sqlite3 "SELECT id, plugin, output_str, status FROM core_archiveresult LIMIT 5;"

# Check Snapshot data preservation
echo "=== ORIGINAL SNAPSHOTS ==="
sqlite3 /path/to/original.db "SELECT id, url, title, added, updated FROM core_snapshot LIMIT 5;"

echo "=== MIGRATED SNAPSHOTS ==="
sqlite3 /tmp/test_vXXX/index.sqlite3 "SELECT id, url, title, bookmarked_at, created_at, modified_at FROM core_snapshot LIMIT 5;"

# Check Tag data preservation
echo "=== ORIGINAL TAGS ==="
sqlite3 /path/to/original.db "SELECT * FROM core_tag;"

echo "=== MIGRATED TAGS ==="
sqlite3 /tmp/test_vXXX/index.sqlite3 "SELECT * FROM core_tag;"

# Check snapshot-tag relationships
sqlite3 /tmp/test_vXXX/index.sqlite3 "SELECT COUNT(*) FROM core_snapshot_tags;"
```

**CRITICAL**: Verify:
- Row counts match
- All URLs, titles, timestamps are preserved
- All extractor values are copied to plugin field
- All output values are copied to output_str field
- All tag relationships are maintained (tag IDs should be converted from UUID to INTEGER for v0.8.6)

## Migration Philosophy

### Principle: Minimal Manual SQL

Use this approach for complex migrations:

1. **Python**: Detect existing schema version
   ```python
   def get_table_columns(table_name):
       cursor = connection.cursor()
       cursor.execute(f"PRAGMA table_info({table_name})")
       return {row[1] for row in cursor.fetchall()}

   cols = get_table_columns('core_archiveresult')
   has_extractor = 'extractor' in cols
   has_plugin = 'plugin' in cols
   ```

2. **SQL**: Modify database structure during migration
   ```sql
   CREATE TABLE core_archiveresult_new (...);
   INSERT INTO core_archiveresult_new SELECT ... FROM core_archiveresult;
   DROP TABLE core_archiveresult;
   ALTER TABLE core_archiveresult_new RENAME TO core_archiveresult;
   ```

3. **Python**: Copy data between old and new field names
   ```python
   if 'extractor' in cols and 'plugin' in cols:
       cursor.execute("UPDATE core_archiveresult SET plugin = COALESCE(extractor, '')")
   ```

4. **SQL**: Drop old columns/tables
   ```sql
   -- Django's RemoveField will handle this
   ```

5. **Django**: Register the end state so Django knows what the schema should be
   ```python
   migrations.SeparateDatabaseAndState(
       database_operations=[...],  # Your SQL/Python migrations
       state_operations=[...]       # Tell Django what the final schema looks like
   )
   ```

### Key Files

- **core/migrations/0023_upgrade_to_0_9_0.py**: Raw SQL migration that upgrades tables from v0.7.2/v0.8.6 schema
  - Should create NEW tables with OLD field names (extractor, output, added, updated)
  - Should preserve ALL data during table rebuild
  - Should NOT add new fields yet (let Django migrations handle that)

- **core/migrations/0025_alter_archiveresult_options_...py**: Django-generated migration
  - Adds new fields (plugin, output_str, bookmarked_at, created_at, etc.)
  - Should include RunPython to copy data from old fields to new fields AFTER AddField operations
  - RemoveField operations to remove old columns

- **crawls/migrations/0002_upgrade_from_0_8_6.py**: Handles crawls_crawl table upgrade
  - v0.8.6 has `seed_id` + `persona` (VARCHAR)
  - v0.9.0 has `urls` + `persona_id` (UUID FK)

## How to Make vs Apply Migrations

### Making Migrations (Creating New Migrations)

**Always run from the archivebox/ subdirectory** (NOT from a data dir):

```bash
cd archivebox/
./manage.py makemigrations
./manage.py makemigrations --check  # Verify no unreflected changes
```

This works because `archivebox/manage.py` has:
```python
os.environ.setdefault('ARCHIVEBOX_DATA_DIR', '.')
```

### Applying Migrations (Testing Migrations)

**Always run from inside a data directory** using `archivebox init`:

```bash
# WRONG - Don't do this:
cd /some/data/dir
../path/to/archivebox/manage.py migrate

# RIGHT - Do this:
DATA_DIR=/some/data/dir python -m archivebox init
```

Why? Because `archivebox init`:
- Sets up the data directory structure
- Runs migrations with proper DATA_DIR context
- Creates necessary files and folders
- Validates the installation

## Schema Version Differences

### v0.7.2 Schema (Migration 0022)
- **ArchiveResult**: `id` (INTEGER), `uuid`, `extractor`, `output`, `cmd`, `pwd`, `cmd_version`, `start_ts`, `end_ts`, `status`, `snapshot_id`
- **Snapshot**: `id`, `url`, `timestamp`, `title`, `added`, `updated`, `crawl_id`
- **Tag**: `id` (INTEGER), `name`, `slug`
- **Crawl**: Doesn't exist in v0.7.2

### v0.8.6rc0 Schema
- **ArchiveResult**: `id`, `abid` (not uuid!), `extractor`, `output`, `created_at`, `modified_at`, `retry_at`, `status`, ...
- **Snapshot**: `id`, `url`, `bookmarked_at`, `created_at`, `modified_at`, `crawl_id`, `status`, `retry_at`, ...
- **Tag**: `id` (UUID/CHAR!), `name`, `slug`, `abid`, `created_at`, `modified_at`, `created_by_id`
- **Crawl**: `id`, `seed_id`, `persona` (VARCHAR), `max_depth`, `tags_str`, `status`, `retry_at`, ...

### v0.9.0 Target Schema
- **ArchiveResult**: `id` (INTEGER), `uuid`, `plugin` (not extractor!), `output_str` (not output!), `hook_name`, `created_at`, `modified_at`, `output_files`, `output_json`, `output_size`, `output_mimetypes`, `retry_at`, ...
- **Snapshot**: `id`, `url`, `bookmarked_at` (not added!), `created_at`, `modified_at` (not updated!), `crawl_id`, `parent_snapshot_id`, `status`, `retry_at`, `current_step`, `depth`, `fs_version`, ...
- **Tag**: `id` (INTEGER!), `name`, `slug`, `created_at`, `modified_at`, `created_by_id`
- **Crawl**: `id`, `urls` (not seed_id!), `persona_id` (not persona!), `label`, `notes`, `output_dir`, ...

## Critical Gotchas and Mistakes to Avoid

### 1. ❌ DON'T Create New Fields in SQL Migration (0023)

**WRONG**:
```python
# In core/migrations/0023_upgrade_to_0_9_0.py
cursor.execute("""
    CREATE TABLE core_archiveresult_new (
        id INTEGER PRIMARY KEY,
        plugin VARCHAR(32),  # ❌ New field!
        output_str TEXT,     # ❌ New field!
        ...
    )
""")
```

**RIGHT**:
```python
# In core/migrations/0023_upgrade_to_0_9_0.py - Keep OLD field names!
cursor.execute("""
    CREATE TABLE core_archiveresult_new (
        id INTEGER PRIMARY KEY,
        extractor VARCHAR(32),  # ✓ OLD field name
        output VARCHAR(1024),   # ✓ OLD field name
        ...
    )
""")
```

**Why**: If you create new fields in SQL, Django's AddField operation in migration 0025 will overwrite them with default values, losing your data!

### 2. ❌ DON'T Copy Data in SQL Migration

**WRONG**:
```python
# In core/migrations/0023
cursor.execute("""
    INSERT INTO core_archiveresult_new (plugin, output_str, ...)
    SELECT COALESCE(extractor, ''), COALESCE(output, ''), ...
    FROM core_archiveresult
""")
```

**RIGHT**: Keep old field names in SQL, let Django AddField create new columns, then copy:
```python
# In core/migrations/0025 (AFTER AddField operations)
def copy_old_to_new(apps, schema_editor):
    cursor = connection.cursor()
    cursor.execute("UPDATE core_archiveresult SET plugin = COALESCE(extractor, '')")
    cursor.execute("UPDATE core_archiveresult SET output_str = COALESCE(output, '')")
```

### 3. ❌ DON'T Assume Empty Tables Mean Fresh Install

**WRONG**:
```python
cursor.execute("SELECT COUNT(*) FROM core_archiveresult")
if cursor.fetchone()[0] == 0:
    return  # Skip migration
```

**Why**: Fresh installs run migrations 0001-0022 which CREATE empty tables with old schema. Migration 0023 must still upgrade the schema even if tables are empty!

**RIGHT**: Detect schema version by checking column names:
```python
cols = get_table_columns('core_archiveresult')
has_extractor = 'extractor' in cols
if has_extractor:
    # Old schema - needs upgrade
```

### 4. ❌ DON'T Run Migrations from Data Directories

**WRONG**:
```bash
cd /path/to/data/dir
python manage.py makemigrations
```

**RIGHT**:
```bash
cd archivebox/  # The archivebox package directory
./manage.py makemigrations
```

### 5. ❌ DON'T Use WHERE Clauses to Skip SQL Selects

**WRONG**:
```sql
INSERT INTO new_table SELECT uuid FROM old_table
WHERE EXISTS (SELECT 1 FROM pragma_table_info('old_table') WHERE name='uuid');
```

**Why**: SQLite still evaluates the `uuid` column reference even if WHERE clause is false, causing "no such column" errors.

**RIGHT**: Use Python to detect schema, then run appropriate SQL:
```python
if 'uuid' in get_table_columns('old_table'):
    cursor.execute("INSERT INTO new_table SELECT uuid FROM old_table")
else:
    cursor.execute("INSERT INTO new_table SELECT abid as uuid FROM old_table")
```

### 6. ❌ DON'T Mix UUID and INTEGER for Tag IDs

v0.8.6rc0 has Tag.id as UUID, but v0.9.0 needs INTEGER. The conversion must:
1. Create mapping of old UUID → new INTEGER
2. Update core_tag with new IDs
3. Update core_snapshot_tags with new tag_id values

See `core/migrations/0023_upgrade_to_0_9_0.py` PART 3 for the correct approach.

### 7. ❌ DON'T Forget SeparateDatabaseAndState

When you manually change the database with SQL, you MUST tell Django what the final state is:

```python
migrations.SeparateDatabaseAndState(
    database_operations=[
        migrations.RunPython(my_sql_function),
    ],
    state_operations=[
        migrations.RemoveField('archiveresult', 'extractor'),
        migrations.RemoveField('archiveresult', 'output'),
    ],
)
```

Without `state_operations`, Django won't know the old fields are gone and `makemigrations --check` will show unreflected changes.

### 8. ✅ DO Print Debug Messages

```python
print(f'Migrating ArchiveResult from v0.7.2 schema...')
print(f'DEBUG: has_uuid={has_uuid}, has_abid={has_abid}, row_count={row_count}')
```

This helps diagnose which migration path is being taken.

### 9. ✅ DO Test All Three Scenarios

Always test:
1. Fresh install (empty database)
2. v0.7.2 upgrade (12 snapshots, 44 archiveresults, 2 tags)
3. v0.8.6rc0 upgrade (14 snapshots, 0 archiveresults, multiple tags with UUIDs)

### 10. ✅ DO Verify No Unreflected Migrations

After all changes:
```bash
cd archivebox/
./manage.py makemigrations --check
# Should output: No changes detected
```

## Current Status

As of 2025-01-01, migrations have these issues:

1. ✅ Fresh install works
2. ✅ v0.7.2 → v0.9.0 migration runs without errors
3. ✅ v0.8.6rc0 → v0.9.0 migration runs without errors
4. ❌ **DATA IS LOST**: `extractor` → `plugin` field data not copied
5. ❌ **DATA IS LOST**: `output` → `output_str` field data not copied
6. ❌ Timestamps (added/updated → bookmarked_at/created_at/modified_at) may have wrong values
7. ❌ Tag relationships may be broken after UUID → INTEGER conversion

## Files That Need Fixing

1. **core/migrations/0023_upgrade_to_0_9_0.py**
   - Line 42-58: CREATE TABLE should use OLD field names (extractor, output, added, updated)
   - Lines 64-88: INSERT SELECT should just copy data as-is, no field renaming yet
   - Remove all references to plugin, output_str, bookmarked_at, created_at - these are added by 0025

2. **core/migrations/0025_...py**
   - Add RunPython operation AFTER all AddField operations
   - This RunPython should copy: extractor→plugin, output→output_str, added→bookmarked_at/created_at, updated→modified_at
   - Fix syntax error on line 28: `{extractor" in cols}` → `{"extractor" in cols}`

3. **crawls/migrations/0002_upgrade_from_0_8_6.py**
   - Already correctly handles conditional upgrade based on schema detection
   - No changes needed if crawls table data isn't critical

## Next Steps

1. Fix core/migrations/0023 to preserve OLD field names
2. Fix core/migrations/0025 to copy data from old → new fields after AddField
3. Remove debug print statements (lines with `print(f'DEBUG:...`)
4. Test all three scenarios
5. Verify data integrity with SQL queries above
6. Run `./manage.py makemigrations --check` to ensure no unreflected changes

## Reference: Field Mappings

| Old Field (v0.7.2/v0.8.6) | New Field (v0.9.0) | Notes |
|---------------------------|-------------------|--------|
| `extractor` | `plugin` | Rename |
| `output` | `output_str` | Rename |
| `added` | `bookmarked_at` | Rename + also use for `created_at` |
| `updated` | `modified_at` | Rename |
| `abid` | `uuid` | v0.8.6 only, field rename |
| Tag.id (UUID) | Tag.id (INTEGER) | v0.8.6 only, type conversion |
| `seed_id` | `urls` | Crawl table, v0.8.6 only |
| `persona` (VARCHAR) | `persona_id` (UUID FK) | Crawl table, v0.8.6 only |

## Testing Checklist

- [ ] Fresh install creates correct schema
- [ ] Fresh install has 0 snapshots, 0 archiveresults
- [ ] v0.7.2 migration preserves all 12 snapshots
- [ ] v0.7.2 migration preserves all 44 archiveresults
- [ ] v0.7.2 migration preserves all 2 tags
- [ ] v0.7.2 migration copies `extractor` → `plugin` (check first 5 rows)
- [ ] v0.7.2 migration copies `output` → `output_str` (check first 5 rows)
- [ ] v0.7.2 migration copies `added` → `bookmarked_at` (compare timestamps)
- [ ] v0.7.2 migration copies `updated` → `modified_at` (compare timestamps)
- [ ] v0.8.6 migration preserves all 14 snapshots
- [ ] v0.8.6 migration converts Tag IDs from UUID → INTEGER
- [ ] v0.8.6 migration preserves tag relationships in core_snapshot_tags
- [ ] v0.8.6 migration converts `abid` → `uuid` field
- [ ] `./manage.py makemigrations --check` shows no changes
- [ ] All migrations run without errors
- [ ] `archivebox status` shows correct snapshot/link counts
