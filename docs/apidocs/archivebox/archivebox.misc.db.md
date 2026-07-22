# {py:mod}`archivebox.misc.db`

```{py:module} archivebox.misc.db
```

```{autodoc2-docstring} archivebox.misc.db
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`run_db_analyze_batch <archivebox.misc.db.run_db_analyze_batch>`
  - ```{autodoc2-docstring} archivebox.misc.db.run_db_analyze_batch
    :summary:
    ```
* - {py:obj}`compact_command <archivebox.misc.db.compact_command>`
  - ```{autodoc2-docstring} archivebox.misc.db.compact_command
    :summary:
    ```
* - {py:obj}`sqlite_lock_holders <archivebox.misc.db.sqlite_lock_holders>`
  - ```{autodoc2-docstring} archivebox.misc.db.sqlite_lock_holders
    :summary:
    ```
* - {py:obj}`log_sqlite_lock_holders <archivebox.misc.db.log_sqlite_lock_holders>`
  - ```{autodoc2-docstring} archivebox.misc.db.log_sqlite_lock_holders
    :summary:
    ```
* - {py:obj}`sqlite_lock_error <archivebox.misc.db.sqlite_lock_error>`
  - ```{autodoc2-docstring} archivebox.misc.db.sqlite_lock_error
    :summary:
    ```
* - {py:obj}`retry_sqlite_locks <archivebox.misc.db.retry_sqlite_locks>`
  - ```{autodoc2-docstring} archivebox.misc.db.retry_sqlite_locks
    :summary:
    ```
* - {py:obj}`migration_lock <archivebox.misc.db.migration_lock>`
  - ```{autodoc2-docstring} archivebox.misc.db.migration_lock
    :summary:
    ```
* - {py:obj}`migration_state <archivebox.misc.db.migration_state>`
  - ```{autodoc2-docstring} archivebox.misc.db.migration_state
    :summary:
    ```
* - {py:obj}`pending_migrations <archivebox.misc.db.pending_migrations>`
  - ```{autodoc2-docstring} archivebox.misc.db.pending_migrations
    :summary:
    ```
* - {py:obj}`apply_migrations <archivebox.misc.db.apply_migrations>`
  - ```{autodoc2-docstring} archivebox.misc.db.apply_migrations
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`HISTORICAL_GHOST_MIGRATIONS <archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS>`
  - ```{autodoc2-docstring} archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS
    :summary:
    ```
````

### API

````{py:function} run_db_analyze_batch(remaining: list[str] | None, *, max_seconds_per_table: float = 120.0) -> list[str]
:canonical: archivebox.misc.db.run_db_analyze_batch

```{autodoc2-docstring} archivebox.misc.db.run_db_analyze_batch
```
````

````{py:function} compact_command(cmdline: list[str] | None, fallback: str = '') -> str
:canonical: archivebox.misc.db.compact_command

```{autodoc2-docstring} archivebox.misc.db.compact_command
```
````

````{py:function} sqlite_lock_holders(db_path: pathlib.Path = CONSTANTS.DATABASE_FILE) -> list[str]
:canonical: archivebox.misc.db.sqlite_lock_holders

```{autodoc2-docstring} archivebox.misc.db.sqlite_lock_holders
```
````

````{py:function} log_sqlite_lock_holders(console: typing.Any, *, db_path: pathlib.Path = CONSTANTS.DATABASE_FILE, limit: int = 8) -> None
:canonical: archivebox.misc.db.log_sqlite_lock_holders

```{autodoc2-docstring} archivebox.misc.db.log_sqlite_lock_holders
```
````

````{py:function} sqlite_lock_error(error: BaseException) -> bool
:canonical: archivebox.misc.db.sqlite_lock_error

```{autodoc2-docstring} archivebox.misc.db.sqlite_lock_error
```
````

````{py:function} retry_sqlite_locks(action: collections.abc.Callable[[], typing.Any], *, label: str, stderr: typing.TextIO | None = None) -> typing.Any
:canonical: archivebox.misc.db.retry_sqlite_locks

```{autodoc2-docstring} archivebox.misc.db.retry_sqlite_locks
```
````

````{py:function} migration_lock(stdout: typing.TextIO | None = None)
:canonical: archivebox.misc.db.migration_lock

```{autodoc2-docstring} archivebox.misc.db.migration_lock
```
````

````{py:data} HISTORICAL_GHOST_MIGRATIONS
:canonical: archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS
:type: frozenset[tuple[str, str]]
:value: >
   'frozenset(...)'

```{autodoc2-docstring} archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS
```

````

````{py:function} migration_state(out_dir: pathlib.Path = CONSTANTS.DATA_DIR) -> tuple[list[str], list[str], dict[str, str]]
:canonical: archivebox.misc.db.migration_state

```{autodoc2-docstring} archivebox.misc.db.migration_state
```
````

````{py:function} pending_migrations(out_dir: pathlib.Path = CONSTANTS.DATA_DIR) -> list[str]
:canonical: archivebox.misc.db.pending_migrations

```{autodoc2-docstring} archivebox.misc.db.pending_migrations
```
````

````{py:function} apply_migrations(out_dir: pathlib.Path = CONSTANTS.DATA_DIR, stdout: typing.TextIO | None = None, stderr: typing.TextIO | None = None, verbosity: int = 1) -> list[str]
:canonical: archivebox.misc.db.apply_migrations

```{autodoc2-docstring} archivebox.misc.db.apply_migrations
```
````
