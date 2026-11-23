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

* - {py:obj}`is_postgres <archivebox.misc.db.is_postgres>`
  - ```{autodoc2-docstring} archivebox.misc.db.is_postgres
    :summary:
    ```
* - {py:obj}`postgres_db_params <archivebox.misc.db.postgres_db_params>`
  - ```{autodoc2-docstring} archivebox.misc.db.postgres_db_params
    :summary:
    ```
* - {py:obj}`_psycopg_connect <archivebox.misc.db._psycopg_connect>`
  - ```{autodoc2-docstring} archivebox.misc.db._psycopg_connect
    :summary:
    ```
* - {py:obj}`database_exists <archivebox.misc.db.database_exists>`
  - ```{autodoc2-docstring} archivebox.misc.db.database_exists
    :summary:
    ```
* - {py:obj}`load_db_secret <archivebox.misc.db.load_db_secret>`
  - ```{autodoc2-docstring} archivebox.misc.db.load_db_secret
    :summary:
    ```
* - {py:obj}`database_display_location <archivebox.misc.db.database_display_location>`
  - ```{autodoc2-docstring} archivebox.misc.db.database_display_location
    :summary:
    ```
* - {py:obj}`ensure_database_ready <archivebox.misc.db.ensure_database_ready>`
  - ```{autodoc2-docstring} archivebox.misc.db.ensure_database_ready
    :summary:
    ```
* - {py:obj}`approximate_row_counts <archivebox.misc.db.approximate_row_counts>`
  - ```{autodoc2-docstring} archivebox.misc.db.approximate_row_counts
    :summary:
    ```
* - {py:obj}`truncate_overlong_charfields <archivebox.misc.db.truncate_overlong_charfields>`
  - ```{autodoc2-docstring} archivebox.misc.db.truncate_overlong_charfields
    :summary:
    ```
* - {py:obj}`rebuild_models_from_migration_state <archivebox.misc.db.rebuild_models_from_migration_state>`
  - ```{autodoc2-docstring} archivebox.misc.db.rebuild_models_from_migration_state
    :summary:
    ```
* - {py:obj}`drop_models_on_postgres <archivebox.misc.db.drop_models_on_postgres>`
  - ```{autodoc2-docstring} archivebox.misc.db.drop_models_on_postgres
    :summary:
    ```
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

* - {py:obj}`_IS_POSTGRES <archivebox.misc.db._IS_POSTGRES>`
  - ```{autodoc2-docstring} archivebox.misc.db._IS_POSTGRES
    :summary:
    ```
* - {py:obj}`HISTORICAL_GHOST_MIGRATIONS <archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS>`
  - ```{autodoc2-docstring} archivebox.misc.db.HISTORICAL_GHOST_MIGRATIONS
    :summary:
    ```
````

### API

````{py:data} _IS_POSTGRES
:canonical: archivebox.misc.db._IS_POSTGRES
:type: bool | None
:value: >
   None

```{autodoc2-docstring} archivebox.misc.db._IS_POSTGRES
```

````

````{py:function} is_postgres(config: typing.Any | None = None) -> bool
:canonical: archivebox.misc.db.is_postgres

```{autodoc2-docstring} archivebox.misc.db.is_postgres
```
````

````{py:function} postgres_db_params() -> dict[str, str]
:canonical: archivebox.misc.db.postgres_db_params

```{autodoc2-docstring} archivebox.misc.db.postgres_db_params
```
````

````{py:function} _psycopg_connect(dbname: str | None = None, connect_timeout: int = 5)
:canonical: archivebox.misc.db._psycopg_connect

```{autodoc2-docstring} archivebox.misc.db._psycopg_connect
```
````

````{py:function} database_exists() -> bool
:canonical: archivebox.misc.db.database_exists

```{autodoc2-docstring} archivebox.misc.db.database_exists
```
````

````{py:function} load_db_secret(config) -> str | None
:canonical: archivebox.misc.db.load_db_secret

```{autodoc2-docstring} archivebox.misc.db.load_db_secret
```
````

````{py:function} database_display_location() -> str
:canonical: archivebox.misc.db.database_display_location

```{autodoc2-docstring} archivebox.misc.db.database_display_location
```
````

````{py:function} ensure_database_ready() -> None
:canonical: archivebox.misc.db.ensure_database_ready

```{autodoc2-docstring} archivebox.misc.db.ensure_database_ready
```
````

````{py:function} approximate_row_counts(connection) -> dict[str, int]
:canonical: archivebox.misc.db.approximate_row_counts

```{autodoc2-docstring} archivebox.misc.db.approximate_row_counts
```
````

````{py:function} truncate_overlong_charfields(instance=None, **kwargs) -> None
:canonical: archivebox.misc.db.truncate_overlong_charfields

```{autodoc2-docstring} archivebox.misc.db.truncate_overlong_charfields
```
````

````{py:function} rebuild_models_from_migration_state(apps, schema_editor, app_label: str, model_names: list[str]) -> None
:canonical: archivebox.misc.db.rebuild_models_from_migration_state

```{autodoc2-docstring} archivebox.misc.db.rebuild_models_from_migration_state
```
````

````{py:function} drop_models_on_postgres(apps, schema_editor, app_label: str, model_names: list[str]) -> None
:canonical: archivebox.misc.db.drop_models_on_postgres

```{autodoc2-docstring} archivebox.misc.db.drop_models_on_postgres
```
````

````{py:function} run_db_analyze_batch(remaining: list[str] | None) -> list[str]
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
