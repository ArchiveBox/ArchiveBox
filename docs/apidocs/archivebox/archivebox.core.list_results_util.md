# {py:mod}`archivebox.core.list_results_util`

```{py:module} archivebox.core.list_results_util
```

```{autodoc2-docstring} archivebox.core.list_results_util
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ListResult <archivebox.core.list_results_util.ListResult>`
  - ```{autodoc2-docstring} archivebox.core.list_results_util.ListResult
    :summary:
    ```
* - {py:obj}`SnapshotListResults <archivebox.core.list_results_util.SnapshotListResults>`
  - ```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`load_snapshot_list_results <archivebox.core.list_results_util.load_snapshot_list_results>`
  - ```{autodoc2-docstring} archivebox.core.list_results_util.load_snapshot_list_results
    :summary:
    ```
* - {py:obj}`_archive_result_from_row <archivebox.core.list_results_util._archive_result_from_row>`
  - ```{autodoc2-docstring} archivebox.core.list_results_util._archive_result_from_row
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_UNRESOLVED <archivebox.core.list_results_util._UNRESOLVED>`
  - ```{autodoc2-docstring} archivebox.core.list_results_util._UNRESOLVED
    :summary:
    ```
````

### API

````{py:data} _UNRESOLVED
:canonical: archivebox.core.list_results_util._UNRESOLVED
:value: >
   'object(...)'

```{autodoc2-docstring} archivebox.core.list_results_util._UNRESOLVED
```

````

`````{py:class} ListResult
:canonical: archivebox.core.list_results_util.ListResult

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult
```

````{py:attribute} id
:canonical: archivebox.core.list_results_util.ListResult.id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.id
```

````

````{py:attribute} snapshot_id
:canonical: archivebox.core.list_results_util.ListResult.snapshot_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.snapshot_id
```

````

````{py:attribute} plugin
:canonical: archivebox.core.list_results_util.ListResult.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.plugin
```

````

````{py:attribute} status
:canonical: archivebox.core.list_results_util.ListResult.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.status
```

````

````{py:attribute} output_size
:canonical: archivebox.core.list_results_util.ListResult.output_size
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.output_size
```

````

````{py:attribute} output_str
:canonical: archivebox.core.list_results_util.ListResult.output_str
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.output_str
```

````

````{py:attribute} output_files_json
:canonical: archivebox.core.list_results_util.ListResult.output_files_json
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.output_files_json
```

````

````{py:attribute} _embed_path
:canonical: archivebox.core.list_results_util.ListResult._embed_path
:type: typing.Any
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult._embed_path
```

````

````{py:attribute} _output_files
:canonical: archivebox.core.list_results_util.ListResult._output_files
:type: dict[str, dict[str, typing.Any]] | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult._output_files
```

````

````{py:method} output_file_map() -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.core.list_results_util.ListResult.output_file_map

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.output_file_map
```

````

````{py:method} embed_path() -> str | None
:canonical: archivebox.core.list_results_util.ListResult.embed_path

```{autodoc2-docstring} archivebox.core.list_results_util.ListResult.embed_path
```

````

`````

`````{py:class} SnapshotListResults
:canonical: archivebox.core.list_results_util.SnapshotListResults

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults
```

````{py:attribute} results
:canonical: archivebox.core.list_results_util.SnapshotListResults.results
:type: list[archivebox.core.list_results_util.ListResult]
:value: >
   'field(...)'

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.results
```

````

````{py:attribute} unnamed_status_counts
:canonical: archivebox.core.list_results_util.SnapshotListResults.unnamed_status_counts
:type: collections.Counter[str]
:value: >
   'field(...)'

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.unnamed_status_counts
```

````

````{py:attribute} thumbnail_result
:canonical: archivebox.core.list_results_util.SnapshotListResults.thumbnail_result
:type: archivebox.core.models.ArchiveResult | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.thumbnail_result
```

````

````{py:property} status_counts
:canonical: archivebox.core.list_results_util.SnapshotListResults.status_counts
:type: collections.Counter[str]

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.status_counts
```

````

````{py:property} output_sizes
:canonical: archivebox.core.list_results_util.SnapshotListResults.output_sizes
:type: dict[str, int]

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.output_sizes
```

````

````{py:method} first_succeeded_by_plugin(*, with_output: bool = False) -> dict[str, archivebox.core.list_results_util.ListResult]
:canonical: archivebox.core.list_results_util.SnapshotListResults.first_succeeded_by_plugin

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.first_succeeded_by_plugin
```

````

````{py:method} succeeded_paths(plugins: set[str]) -> list[str]
:canonical: archivebox.core.list_results_util.SnapshotListResults.succeeded_paths

```{autodoc2-docstring} archivebox.core.list_results_util.SnapshotListResults.succeeded_paths
```

````

`````

````{py:function} load_snapshot_list_results(snapshots: collections.abc.Iterable[typing.Any]) -> dict[typing.Any, archivebox.core.list_results_util.SnapshotListResults]
:canonical: archivebox.core.list_results_util.load_snapshot_list_results

```{autodoc2-docstring} archivebox.core.list_results_util.load_snapshot_list_results
```
````

````{py:function} _archive_result_from_row(row: archivebox.core.list_results_util.ListResult) -> archivebox.core.models.ArchiveResult
:canonical: archivebox.core.list_results_util._archive_result_from_row

```{autodoc2-docstring} archivebox.core.list_results_util._archive_result_from_row
```
````
