# {py:mod}`archivebox.services.snapshot_service`

```{py:module} archivebox.services.snapshot_service
```

```{autodoc2-docstring} archivebox.services.snapshot_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SnapshotService <archivebox.services.snapshot_service.SnapshotService>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`project_discovered_snapshots <archivebox.services.snapshot_service.project_discovered_snapshots>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.project_discovered_snapshots
    :summary:
    ```
* - {py:obj}`finalize_completed_snapshot <archivebox.services.snapshot_service.finalize_completed_snapshot>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.finalize_completed_snapshot
    :summary:
    ```
* - {py:obj}`_crawl_limit_stop_reason <archivebox.services.snapshot_service._crawl_limit_stop_reason>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service._crawl_limit_stop_reason
    :summary:
    ```
````

### API

````{py:function} project_discovered_snapshots(snapshot_id: str) -> list
:canonical: archivebox.services.snapshot_service.project_discovered_snapshots

```{autodoc2-docstring} archivebox.services.snapshot_service.project_discovered_snapshots
```
````

````{py:function} finalize_completed_snapshot(snapshot_id: str, *, output_dir=None, crawl_limit_stop_reason: str | None = None) -> None
:canonical: archivebox.services.snapshot_service.finalize_completed_snapshot

```{autodoc2-docstring} archivebox.services.snapshot_service.finalize_completed_snapshot
```
````

````{py:function} _crawl_limit_stop_reason(crawl) -> str
:canonical: archivebox.services.snapshot_service._crawl_limit_stop_reason

```{autodoc2-docstring} archivebox.services.snapshot_service._crawl_limit_stop_reason
```
````

`````{py:class} SnapshotService(bus, *, crawl_id: str)
:canonical: archivebox.services.snapshot_service.SnapshotService

Bases: {py:obj}`abx_dl.services.base.BaseService`

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.snapshot_service.SnapshotService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.snapshot_service.SnapshotService.EMITS
:value: >
   []

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.EMITS
```

````

````{py:method} on_SnapshotEvent(event: abx_dl.events.SnapshotEvent) -> None
:canonical: archivebox.services.snapshot_service.SnapshotService.on_SnapshotEvent
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.on_SnapshotEvent
```

````

````{py:method} on_SnapshotCompletedEvent(event: abx_dl.events.SnapshotCompletedEvent) -> None
:canonical: archivebox.services.snapshot_service.SnapshotService.on_SnapshotCompletedEvent
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.on_SnapshotCompletedEvent
```

````

`````
