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

* - {py:obj}`ModelDumpable <archivebox.services.archive_result_service.ModelDumpable>`
  -
* - {py:obj}`ArchiveResultService <archivebox.services.archive_result_service.ArchiveResultService>`
  -
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
* - {py:obj}`_collect_output_metadata <archivebox.services.archive_result_service._collect_output_metadata>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._collect_output_metadata
    :summary:
    ```
* - {py:obj}`_coerce_output_file_size <archivebox.services.archive_result_service._coerce_output_file_size>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._coerce_output_file_size
    :summary:
    ```
* - {py:obj}`_normalize_output_files <archivebox.services.archive_result_service._normalize_output_files>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_output_files
    :summary:
    ```
* - {py:obj}`_has_structured_output_metadata <archivebox.services.archive_result_service._has_structured_output_metadata>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._has_structured_output_metadata
    :summary:
    ```
* - {py:obj}`_summarize_output_files <archivebox.services.archive_result_service._summarize_output_files>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._summarize_output_files
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
* - {py:obj}`_normalize_snapshot_title <archivebox.services.archive_result_service._normalize_snapshot_title>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_snapshot_title
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
* - {py:obj}`_status_for_process_without_archive_result <archivebox.services.archive_result_service._status_for_process_without_archive_result>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._status_for_process_without_archive_result
    :summary:
    ```
* - {py:obj}`_iter_archiveresult_records <archivebox.services.archive_result_service._iter_archiveresult_records>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._iter_archiveresult_records
    :summary:
    ```
* - {py:obj}`_save_archiveresult_event_to_db <archivebox.services.archive_result_service._save_archiveresult_event_to_db>`
  - ```{autodoc2-docstring} archivebox.services.archive_result_service._save_archiveresult_event_to_db
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

`````{py:class} ModelDumpable
:canonical: archivebox.services.archive_result_service.ModelDumpable

Bases: {py:obj}`typing.Protocol`

````{py:method} model_dump() -> dict[str, typing.Any]
:canonical: archivebox.services.archive_result_service.ModelDumpable.model_dump

```{autodoc2-docstring} archivebox.services.archive_result_service.ModelDumpable.model_dump
```

````

`````

````{py:function} _collect_output_metadata(plugin_dir: pathlib.Path) -> tuple[dict[str, dict], int, str]
:canonical: archivebox.services.archive_result_service._collect_output_metadata

```{autodoc2-docstring} archivebox.services.archive_result_service._collect_output_metadata
```
````

````{py:function} _coerce_output_file_size(value: typing.Any) -> int
:canonical: archivebox.services.archive_result_service._coerce_output_file_size

```{autodoc2-docstring} archivebox.services.archive_result_service._coerce_output_file_size
```
````

````{py:function} _normalize_output_files(raw_output_files: typing.Any) -> dict[str, dict]
:canonical: archivebox.services.archive_result_service._normalize_output_files

```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_output_files
```
````

````{py:function} _has_structured_output_metadata(output_files: dict[str, dict]) -> bool
:canonical: archivebox.services.archive_result_service._has_structured_output_metadata

```{autodoc2-docstring} archivebox.services.archive_result_service._has_structured_output_metadata
```
````

````{py:function} _summarize_output_files(output_files: dict[str, dict]) -> tuple[int, str]
:canonical: archivebox.services.archive_result_service._summarize_output_files

```{autodoc2-docstring} archivebox.services.archive_result_service._summarize_output_files
```
````

````{py:function} _resolve_output_metadata(raw_output_files: typing.Any, plugin_dir: pathlib.Path) -> tuple[dict[str, dict], int, str]
:canonical: archivebox.services.archive_result_service._resolve_output_metadata

```{autodoc2-docstring} archivebox.services.archive_result_service._resolve_output_metadata
```
````

````{py:function} _normalize_status(status: str) -> str
:canonical: archivebox.services.archive_result_service._normalize_status

```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_status
```
````

````{py:function} _normalize_snapshot_title(candidate: str, *, snapshot_url: str) -> str
:canonical: archivebox.services.archive_result_service._normalize_snapshot_title

```{autodoc2-docstring} archivebox.services.archive_result_service._normalize_snapshot_title
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

````{py:function} _status_for_process_without_archive_result(event: abx_dl.events.ProcessCompletedEvent) -> str
:canonical: archivebox.services.archive_result_service._status_for_process_without_archive_result

```{autodoc2-docstring} archivebox.services.archive_result_service._status_for_process_without_archive_result
```
````

````{py:function} _iter_archiveresult_records(stdout: str) -> list[dict]
:canonical: archivebox.services.archive_result_service._iter_archiveresult_records

```{autodoc2-docstring} archivebox.services.archive_result_service._iter_archiveresult_records
```
````

````{py:function} _save_archiveresult_event_to_db(event: abx_dl.events.ArchiveResultEvent, process_started: abx_dl.events.ProcessStartedEvent | None) -> None
:canonical: archivebox.services.archive_result_service._save_archiveresult_event_to_db

```{autodoc2-docstring} archivebox.services.archive_result_service._save_archiveresult_event_to_db
```
````

`````{py:class} ArchiveResultService(bus)
:canonical: archivebox.services.archive_result_service.ArchiveResultService

Bases: {py:obj}`abx_dl.services.base.BaseService`

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

````{py:method} on_ProcessCompletedEvent__save_to_db(event: abx_dl.events.ProcessCompletedEvent) -> None
:canonical: archivebox.services.archive_result_service.ArchiveResultService.on_ProcessCompletedEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.archive_result_service.ArchiveResultService.on_ProcessCompletedEvent__save_to_db
```

````

`````
