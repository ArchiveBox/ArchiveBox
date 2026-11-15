# {py:mod}`archivebox.cli.rescan`

```{py:module} archivebox.cli.rescan
```

```{autodoc2-docstring} archivebox.cli.rescan
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_directories <archivebox.cli.rescan._directories>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._directories
    :summary:
    ```
* - {py:obj}`_snapshot_directories <archivebox.cli.rescan._snapshot_directories>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._snapshot_directories
    :summary:
    ```
* - {py:obj}`_fields <archivebox.cli.rescan._fields>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._fields
    :summary:
    ```
* - {py:obj}`_dates <archivebox.cli.rescan._dates>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._dates
    :summary:
    ```
* - {py:obj}`_restore_dates <archivebox.cli.rescan._restore_dates>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._restore_dates
    :summary:
    ```
* - {py:obj}`_reconcile_unattributed_output_size <archivebox.cli.rescan._reconcile_unattributed_output_size>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._reconcile_unattributed_output_size
    :summary:
    ```
* - {py:obj}`_reconcile_directory <archivebox.cli.rescan._reconcile_directory>`
  - ```{autodoc2-docstring} archivebox.cli.rescan._reconcile_directory
    :summary:
    ```
* - {py:obj}`reconcile_known_snapshots <archivebox.cli.rescan.reconcile_known_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.rescan.reconcile_known_snapshots
    :summary:
    ```
* - {py:obj}`rescan_snapshots <archivebox.cli.rescan.rescan_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.rescan.rescan_snapshots
    :summary:
    ```
````

### API

````{py:function} _directories(parent: pathlib.Path)
:canonical: archivebox.cli.rescan._directories

```{autodoc2-docstring} archivebox.cli.rescan._directories
```
````

````{py:function} _snapshot_directories(reverse=False)
:canonical: archivebox.cli.rescan._snapshot_directories

```{autodoc2-docstring} archivebox.cli.rescan._snapshot_directories
```
````

````{py:function} _fields(record, names)
:canonical: archivebox.cli.rescan._fields

```{autodoc2-docstring} archivebox.cli.rescan._fields
```
````

````{py:function} _dates(record)
:canonical: archivebox.cli.rescan._dates

```{autodoc2-docstring} archivebox.cli.rescan._dates
```
````

````{py:function} _restore_dates(obj, record)
:canonical: archivebox.cli.rescan._restore_dates

```{autodoc2-docstring} archivebox.cli.rescan._restore_dates
```
````

````{py:function} _reconcile_unattributed_output_size(snapshot: archivebox.core.models.Snapshot, directory: pathlib.Path) -> bool
:canonical: archivebox.cli.rescan._reconcile_unattributed_output_size

```{autodoc2-docstring} archivebox.cli.rescan._reconcile_unattributed_output_size
```
````

````{py:function} _reconcile_directory(directory: pathlib.Path, *, repair_unattributed_size: bool = False) -> str
:canonical: archivebox.cli.rescan._reconcile_directory

```{autodoc2-docstring} archivebox.cli.rescan._reconcile_directory
```
````

````{py:function} reconcile_known_snapshots(snapshots, wait_for_turn=None, *, repair_unattributed_size=False)
:canonical: archivebox.cli.rescan.reconcile_known_snapshots

```{autodoc2-docstring} archivebox.cli.rescan.reconcile_known_snapshots
```
````

````{py:function} rescan_snapshots(wait_for_turn=None, reverse=False, scan_legacy=None)
:canonical: archivebox.cli.rescan.rescan_snapshots

```{autodoc2-docstring} archivebox.cli.rescan.rescan_snapshots
```
````
