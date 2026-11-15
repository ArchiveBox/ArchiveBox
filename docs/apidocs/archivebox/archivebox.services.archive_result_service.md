# {py:mod}`archivebox.services.archive_result_service`

```{py:module} archivebox.services.archive_result_service
```

```{autodoc2-docstring} archivebox.services.archive_result_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveResultService <archivebox.services.archive_result_service.ArchiveResultService>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_perf_trace <archivebox.services.archive_result_service._perf_trace>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._perf_trace
    :summary:
    ```
* - {py:obj}`_perf_span <archivebox.services.archive_result_service._perf_span>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._perf_span
    :summary:
    ```
* - {py:obj}`_manifest_metadata <archivebox.services.archive_result_service._manifest_metadata>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._manifest_metadata
    :summary:
    ```
* - {py:obj}`_resolve_output_metadata <archivebox.services.archive_result_service._resolve_output_metadata>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._resolve_output_metadata
    :summary:
    ```
* - {py:obj}`_normalize_status <archivebox.services.archive_result_service._normalize_status>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_status
    :summary:
    ```
* - {py:obj}`_extract_snapshot_title <archivebox.services.archive_result_service._extract_snapshot_title>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._extract_snapshot_title
    :summary:
    ```
* - {py:obj}`_should_update_snapshot_title <archivebox.services.archive_result_service._should_update_snapshot_title>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._should_update_snapshot_title
    :summary:
    ```
* - {py:obj}`_save_archiveresult_event_to_db <archivebox.services.archive_result_service._save_archiveresult_event_to_db>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._save_archiveresult_event_to_db
    :summary:
    ```
* - {py:obj}`_read_archiveresult_outputs <archivebox.services.archive_result_service._read_archiveresult_outputs>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._read_archiveresult_outputs
    :summary:
    ```
* - {py:obj}`_save_snapshot_title <archivebox.services.archive_result_service._save_snapshot_title>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._save_snapshot_title
    :summary:
    ```
* - {py:obj}`mark_archiveresult_started <archivebox.services.archive_result_service.mark_archiveresult_started>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service.mark_archiveresult_started
    :summary:
    ```
````

### API

````{py:function} _perf_trace(label)
:canonical: archivebox.services.archive_result_service._perf_trace

```{autodoc2-docstring} archivebox.services.archive_result_service._perf_trace
```
````

````{py:function} _perf_span(label: str)
:canonical: archivebox.services.archive_result_service._perf_span

```{autodoc2-docstring} archivebox.services.archive_result_service._perf_span
```
````

````{py:function} _manifest_metadata(manifest: abx_dl.output_files.OutputManifest) -> tuple[dict[str, dict], int, str]
:canonical: archivebox.services.archive_result_service._manifest_metadata

```{autodoc2-docstring} archivebox.services.archive_result_service._manifest_metadata
```
````

````{py:function} _resolve_output_metadata(raw_output_files: typing.Any) -> tuple[dict[str, dict], int, str]
:canonical: archivebox.services.archive_result_service._resolve_output_metadata

```{autodoc2-docstring} archivebox.services.archive_result_service._resolve_output_metadata
```
````

````{py:function} _normalize_status(status: str) -> str
:canonical: archivebox.services.archive_result_service._normalize_status

```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_status
```
````

````{py:function} _extract_snapshot_title(snapshot_output_dir: str, plugin: str, output_str: str, *, snapshot_url: str) -> str
:canonical: archivebox.services.archive_result_service._extract_snapshot_title

```{autodoc2-docstring} archivebox.services.archive_result_service._extract_snapshot_title
```
````

````{py:function} _should_update_snapshot_title(current_title: str, next_title: str, *, snapshot_url: str) -> bool
:canonical: archivebox.services.archive_result_service._should_update_snapshot_title

```{autodoc2-docstring} archivebox.services.archive_result_service._should_update_snapshot_title
```
````

````{py:function} _save_archiveresult_event_to_db(event: abx_dl.events.ArchiveResultEvent, process_started: abx_dl.events.ProcessStartedEvent | abx_dl.events.ProcessCompletedEvent | None) -> archivebox.core.models.Snapshot | None
:canonical: archivebox.services.archive_result_service._save_archiveresult_event_to_db

```{autodoc2-docstring} archivebox.services.archive_result_service._save_archiveresult_event_to_db
```
````

````{py:function} _read_archiveresult_outputs(snapshot: archivebox.core.models.Snapshot, event: abx_dl.events.ArchiveResultEvent, process_started: abx_dl.events.ProcessStartedEvent | abx_dl.events.ProcessCompletedEvent | None) -> tuple[str, bool]
:canonical: archivebox.services.archive_result_service._read_archiveresult_outputs

```{autodoc2-docstring} archivebox.services.archive_result_service._read_archiveresult_outputs
```
````

````{py:function} _save_snapshot_title(snapshot_id: str, next_title: str) -> None
:canonical: archivebox.services.archive_result_service._save_snapshot_title

```{autodoc2-docstring} archivebox.services.archive_result_service._save_snapshot_title
```
````

````{py:function} mark_archiveresult_started(event: abx_dl.events.ProcessStartedEvent, *, snapshot_id: str, process_id: str) -> None
:canonical: archivebox.services.archive_result_service.mark_archiveresult_started

```{autodoc2-docstring} archivebox.services.archive_result_service.mark_archiveresult_started
```
````

`````{py:class} ArchiveResultService(bus)
:canonical: archivebox.services.archive_result_service.ArchiveResultService

Bases: {py:obj}`abx_dl.services.base.BaseService`

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService.__init__
```

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.archive_result_service.ArchiveResultService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.archive_result_service.ArchiveResultService.EMITS
:value: >
   []

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService.EMITS
```

````

````{py:method} on_ArchiveResultEvent__save_to_db(event: abx_dl.events.ArchiveResultEvent) -> None
:canonical: archivebox.services.archive_result_service.ArchiveResultService.on_ArchiveResultEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService.on_ArchiveResultEvent__save_to_db
```

````

`````
