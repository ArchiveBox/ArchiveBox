# {py:mod}`archivebox.core.snapshot_status`

```{py:module} archivebox.core.snapshot_status
```

```{autodoc2-docstring} archivebox.core.snapshot_status
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`snapshot_status_values <archivebox.core.snapshot_status.snapshot_status_values>`
  - ```{autodoc2-docstring} archivebox.core.snapshot_status.snapshot_status_values
    :summary:
    ```
* - {py:obj}`normalize_snapshot_status <archivebox.core.snapshot_status.normalize_snapshot_status>`
  - ```{autodoc2-docstring} archivebox.core.snapshot_status.normalize_snapshot_status
    :summary:
    ```
* - {py:obj}`filter_snapshots_by_status <archivebox.core.snapshot_status.filter_snapshots_by_status>`
  - ```{autodoc2-docstring} archivebox.core.snapshot_status.filter_snapshots_by_status
    :summary:
    ```
````

### API

````{py:function} snapshot_status_values() -> tuple[str, ...]
:canonical: archivebox.core.snapshot_status.snapshot_status_values

```{autodoc2-docstring} archivebox.core.snapshot_status.snapshot_status_values
```
````

````{py:function} normalize_snapshot_status(status: str | None) -> str | None
:canonical: archivebox.core.snapshot_status.normalize_snapshot_status

```{autodoc2-docstring} archivebox.core.snapshot_status.normalize_snapshot_status
```
````

````{py:function} filter_snapshots_by_status(queryset: django.db.models.QuerySet, status: str | None) -> django.db.models.QuerySet
:canonical: archivebox.core.snapshot_status.filter_snapshots_by_status

```{autodoc2-docstring} archivebox.core.snapshot_status.filter_snapshots_by_status
```
````
