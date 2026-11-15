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
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_load_discovery_context <archivebox.services.snapshot_service._load_discovery_context>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service._load_discovery_context
    :summary:
    ```
* - {py:obj}`_read_discovery_outputs <archivebox.services.snapshot_service._read_discovery_outputs>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service._read_discovery_outputs
    :summary:
    ```
* - {py:obj}`_project_discovered_snapshots <archivebox.services.snapshot_service._project_discovered_snapshots>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service._project_discovered_snapshots
    :summary:
    ```
* - {py:obj}`project_discovered_snapshots <archivebox.services.snapshot_service.project_discovered_snapshots>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.project_discovered_snapshots
    :summary:
    ```
* - {py:obj}`aproject_discovered_snapshots <archivebox.services.snapshot_service.aproject_discovered_snapshots>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.aproject_discovered_snapshots
    :summary:
    ```
* - {py:obj}`prepare_completed_snapshot <archivebox.services.snapshot_service.prepare_completed_snapshot>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service.prepare_completed_snapshot
    :summary:
    ```
* - {py:obj}`_project_snapshot_error <archivebox.services.snapshot_service._project_snapshot_error>`
  - ```{autodoc2-docstring} archivebox.services.snapshot_service._project_snapshot_error
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

````{py:function} _load_discovery_context(snapshot_id: str)
:canonical: archivebox.services.snapshot_service._load_discovery_context

```{autodoc2-docstring} archivebox.services.snapshot_service._load_discovery_context
```
````

````{py:function} _read_discovery_outputs(context)
:canonical: archivebox.services.snapshot_service._read_discovery_outputs

```{autodoc2-docstring} archivebox.services.snapshot_service._read_discovery_outputs
```
````

````{py:function} _project_discovered_snapshots(context, output) -> list
:canonical: archivebox.services.snapshot_service._project_discovered_snapshots

```{autodoc2-docstring} archivebox.services.snapshot_service._project_discovered_snapshots
```
````

````{py:function} project_discovered_snapshots(snapshot_id: str) -> list
:canonical: archivebox.services.snapshot_service.project_discovered_snapshots

```{autodoc2-docstring} archivebox.services.snapshot_service.project_discovered_snapshots
```
````

````{py:function} aproject_discovered_snapshots(snapshot_id: str) -> list
:canonical: archivebox.services.snapshot_service.aproject_discovered_snapshots
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.aproject_discovered_snapshots
```
````

````{py:function} prepare_completed_snapshot(snapshot_id: str, *, owned_retry_at, was_sealed: bool, error: str = '')
:canonical: archivebox.services.snapshot_service.prepare_completed_snapshot

```{autodoc2-docstring} archivebox.services.snapshot_service.prepare_completed_snapshot
```
````

````{py:function} _project_snapshot_error(snapshot, error: str) -> None
:canonical: archivebox.services.snapshot_service._project_snapshot_error

```{autodoc2-docstring} archivebox.services.snapshot_service._project_snapshot_error
```
````

````{py:function} finalize_completed_snapshot(snapshot_id: str, *, owned_retry_at, was_sealed: bool, consumed_retry_plugins: list[str] | None = None, published_modified_at: datetime.datetime | None = None, error: str = '') -> None
:canonical: archivebox.services.snapshot_service.finalize_completed_snapshot

```{autodoc2-docstring} archivebox.services.snapshot_service.finalize_completed_snapshot
```
````

````{py:function} _crawl_limit_stop_reason(crawl) -> str
:canonical: archivebox.services.snapshot_service._crawl_limit_stop_reason

```{autodoc2-docstring} archivebox.services.snapshot_service._crawl_limit_stop_reason
```
````

`````{py:class} SnapshotService(bus, *, crawl_id: str, interrupted: collections.abc.Callable[[], bool] | None = None)
:canonical: archivebox.services.snapshot_service.SnapshotService

Bases: {py:obj}`abx_dl.services.base.BaseService`

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.__init__
```

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

````{py:method} on_SnapshotCleanupEvent(event: abx_dl.events.SnapshotCleanupEvent) -> None
:canonical: archivebox.services.snapshot_service.SnapshotService.on_SnapshotCleanupEvent
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.on_SnapshotCleanupEvent
```

````

````{py:method} renew_lease(snapshot_id: str, lease_until) -> bool | None
:canonical: archivebox.services.snapshot_service.SnapshotService.renew_lease
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.renew_lease
```

````

````{py:method} on_SnapshotCompletedEvent(event: abx_dl.events.SnapshotCompletedEvent) -> None
:canonical: archivebox.services.snapshot_service.SnapshotService.on_SnapshotCompletedEvent
:async:

```{autodoc2-docstring} archivebox.services.snapshot_service.SnapshotService.on_SnapshotCompletedEvent
```

````

`````
