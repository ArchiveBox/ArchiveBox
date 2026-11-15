# {py:mod}`archivebox.cli.archivebox_extract`

```{py:module} archivebox.cli.archivebox_extract
```

```{autodoc2-docstring} archivebox.cli.archivebox_extract
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_resolve_requests <archivebox.cli.archivebox_extract._resolve_requests>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract._resolve_requests
    :summary:
    ```
* - {py:obj}`_run_snapshot_requests <archivebox.cli.archivebox_extract._run_snapshot_requests>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract._run_snapshot_requests
    :summary:
    ```
* - {py:obj}`run_plugins <archivebox.cli.archivebox_extract.run_plugins>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract.run_plugins
    :summary:
    ```
* - {py:obj}`process_archiveresult_by_id <archivebox.cli.archivebox_extract.process_archiveresult_by_id>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract.process_archiveresult_by_id
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_extract.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract.main
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_extract.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_extract.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_extract.__command__
:value: >
   'archivebox extract'

```{autodoc2-docstring} archivebox.cli.archivebox_extract.__command__
```

````

````{py:function} _resolve_requests(records: list[dict], plugins: str) -> tuple[dict[str, set[str]], set[str]]
:canonical: archivebox.cli.archivebox_extract._resolve_requests

```{autodoc2-docstring} archivebox.cli.archivebox_extract._resolve_requests
```
````

````{py:function} _run_snapshot_requests(requested: dict[str, set[str]], *, wait: bool, show_progress: bool) -> int
:canonical: archivebox.cli.archivebox_extract._run_snapshot_requests

```{autodoc2-docstring} archivebox.cli.archivebox_extract._run_snapshot_requests
```
````

````{py:function} run_plugins(args: tuple, records: list[dict] | None = None, plugins: str = '', wait: bool = True, emit_results: bool = True, show_progress: bool = True) -> int
:canonical: archivebox.cli.archivebox_extract.run_plugins

```{autodoc2-docstring} archivebox.cli.archivebox_extract.run_plugins
```
````

````{py:function} process_archiveresult_by_id(archiveresult_id: str) -> int
:canonical: archivebox.cli.archivebox_extract.process_archiveresult_by_id

```{autodoc2-docstring} archivebox.cli.archivebox_extract.process_archiveresult_by_id
```
````

````{py:function} main(plugins: str, wait: bool, args: tuple)
:canonical: archivebox.cli.archivebox_extract.main

```{autodoc2-docstring} archivebox.cli.archivebox_extract.main
```
````
