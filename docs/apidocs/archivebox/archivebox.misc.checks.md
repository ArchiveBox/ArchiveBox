# {py:mod}`archivebox.misc.checks`

```{py:module} archivebox.misc.checks
```

```{autodoc2-docstring} archivebox.misc.checks
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_migration_interrupt_message <archivebox.misc.checks._migration_interrupt_message>`
  - ```{autodoc2-docstring} archivebox.misc.checks._migration_interrupt_message
    :summary:
    ```
* - {py:obj}`_exit_on_migration_interrupt <archivebox.misc.checks._exit_on_migration_interrupt>`
  - ```{autodoc2-docstring} archivebox.misc.checks._exit_on_migration_interrupt
    :summary:
    ```
* - {py:obj}`check_data_folder <archivebox.misc.checks.check_data_folder>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_data_folder
    :summary:
    ```
* - {py:obj}`check_migrations <archivebox.misc.checks.check_migrations>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_migrations
    :summary:
    ```
* - {py:obj}`check_io_encoding <archivebox.misc.checks.check_io_encoding>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_io_encoding
    :summary:
    ```
* - {py:obj}`check_not_root <archivebox.misc.checks.check_not_root>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_not_root
    :summary:
    ```
* - {py:obj}`check_not_inside_source_dir <archivebox.misc.checks.check_not_inside_source_dir>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_not_inside_source_dir
    :summary:
    ```
* - {py:obj}`check_data_dir_permissions <archivebox.misc.checks.check_data_dir_permissions>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_data_dir_permissions
    :summary:
    ```
* - {py:obj}`check_tmp_dir <archivebox.misc.checks.check_tmp_dir>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_tmp_dir
    :summary:
    ```
* - {py:obj}`check_lib_dir <archivebox.misc.checks.check_lib_dir>`
  - ```{autodoc2-docstring} archivebox.misc.checks.check_lib_dir
    :summary:
    ```
````

### API

````{py:function} _migration_interrupt_message(*, before_apply: bool = False) -> str
:canonical: archivebox.misc.checks._migration_interrupt_message

```{autodoc2-docstring} archivebox.misc.checks._migration_interrupt_message
```
````

````{py:function} _exit_on_migration_interrupt()
:canonical: archivebox.misc.checks._exit_on_migration_interrupt

```{autodoc2-docstring} archivebox.misc.checks._exit_on_migration_interrupt
```
````

````{py:function} check_data_folder(config=None, **config_kwargs) -> None
:canonical: archivebox.misc.checks.check_data_folder

```{autodoc2-docstring} archivebox.misc.checks.check_data_folder
```
````

````{py:function} check_migrations(*, blocking: bool = True, auto_apply: bool = False, cancel_delay: int = 3) -> list[str]
:canonical: archivebox.misc.checks.check_migrations

```{autodoc2-docstring} archivebox.misc.checks.check_migrations
```
````

````{py:function} check_io_encoding()
:canonical: archivebox.misc.checks.check_io_encoding

```{autodoc2-docstring} archivebox.misc.checks.check_io_encoding
```
````

````{py:function} check_not_root()
:canonical: archivebox.misc.checks.check_not_root

```{autodoc2-docstring} archivebox.misc.checks.check_not_root
```
````

````{py:function} check_not_inside_source_dir()
:canonical: archivebox.misc.checks.check_not_inside_source_dir

```{autodoc2-docstring} archivebox.misc.checks.check_not_inside_source_dir
```
````

````{py:function} check_data_dir_permissions(config=None, **config_kwargs)
:canonical: archivebox.misc.checks.check_data_dir_permissions

```{autodoc2-docstring} archivebox.misc.checks.check_data_dir_permissions
```
````

````{py:function} check_tmp_dir(tmp_dir=None, throw=False, quiet=False, must_exist=True, config=None, **config_kwargs)
:canonical: archivebox.misc.checks.check_tmp_dir

```{autodoc2-docstring} archivebox.misc.checks.check_tmp_dir
```
````

````{py:function} check_lib_dir(lib_dir: pathlib.Path | None = None, throw=False, quiet=False, must_exist=True, config=None, **config_kwargs)
:canonical: archivebox.misc.checks.check_lib_dir

```{autodoc2-docstring} archivebox.misc.checks.check_lib_dir
```
````
