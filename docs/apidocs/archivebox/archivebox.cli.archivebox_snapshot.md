# {py:mod}`archivebox.cli.archivebox_snapshot`

```{py:module} archivebox.cli.archivebox_snapshot
```

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`iter_snapshot_json <archivebox.cli.archivebox_snapshot.iter_snapshot_json>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.iter_snapshot_json
    :summary:
    ```
* - {py:obj}`create_snapshots <archivebox.cli.archivebox_snapshot.create_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.create_snapshots
    :summary:
    ```
* - {py:obj}`snapshot_filter_options <archivebox.cli.archivebox_snapshot.snapshot_filter_options>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.snapshot_filter_options
    :summary:
    ```
* - {py:obj}`snapshot_output_options <archivebox.cli.archivebox_snapshot.snapshot_output_options>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.snapshot_output_options
    :summary:
    ```
* - {py:obj}`build_snapshot_queryset <archivebox.cli.archivebox_snapshot.build_snapshot_queryset>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.build_snapshot_queryset
    :summary:
    ```
* - {py:obj}`list_snapshots <archivebox.cli.archivebox_snapshot.list_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.list_snapshots
    :summary:
    ```
* - {py:obj}`update_snapshots <archivebox.cli.archivebox_snapshot.update_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.update_snapshots
    :summary:
    ```
* - {py:obj}`delete_snapshots <archivebox.cli.archivebox_snapshot.delete_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.delete_snapshots
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_snapshot.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.main
    :summary:
    ```
* - {py:obj}`create_cmd <archivebox.cli.archivebox_snapshot.create_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.create_cmd
    :summary:
    ```
* - {py:obj}`list_cmd <archivebox.cli.archivebox_snapshot.list_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.list_cmd
    :summary:
    ```
* - {py:obj}`update_cmd <archivebox.cli.archivebox_snapshot.update_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.update_cmd
    :summary:
    ```
* - {py:obj}`delete_cmd <archivebox.cli.archivebox_snapshot.delete_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.delete_cmd
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_snapshot.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.__command__
    :summary:
    ```
* - {py:obj}`SNAPSHOT_FILTER_TYPE_CHOICES <archivebox.cli.archivebox_snapshot.SNAPSHOT_FILTER_TYPE_CHOICES>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.SNAPSHOT_FILTER_TYPE_CHOICES
    :summary:
    ```
* - {py:obj}`SNAPSHOT_LIST_CHUNK_SIZE <archivebox.cli.archivebox_snapshot.SNAPSHOT_LIST_CHUNK_SIZE>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.SNAPSHOT_LIST_CHUNK_SIZE
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_snapshot.__command__
:value: >
   'archivebox snapshot'

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.__command__
```

````

````{py:data} SNAPSHOT_FILTER_TYPE_CHOICES
:canonical: archivebox.cli.archivebox_snapshot.SNAPSHOT_FILTER_TYPE_CHOICES
:value: >
   ('exact', 'substring', 'regex', 'domain', 'tag', 'timestamp')

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.SNAPSHOT_FILTER_TYPE_CHOICES
```

````

````{py:data} SNAPSHOT_LIST_CHUNK_SIZE
:canonical: archivebox.cli.archivebox_snapshot.SNAPSHOT_LIST_CHUNK_SIZE
:value: >
   5000

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.SNAPSHOT_LIST_CHUNK_SIZE
```

````

````{py:function} iter_snapshot_json(queryset: django.db.models.QuerySet) -> collections.abc.Iterator[dict[str, object]]
:canonical: archivebox.cli.archivebox_snapshot.iter_snapshot_json

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.iter_snapshot_json
```
````

````{py:function} create_snapshots(urls: collections.abc.Iterable[str], tag: str = '', status: str = 'queued', depth: int = 0, created_by_id: int | None = None) -> int
:canonical: archivebox.cli.archivebox_snapshot.create_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.create_snapshots
```
````

````{py:function} snapshot_filter_options(*, default_filter_type: str)
:canonical: archivebox.cli.archivebox_snapshot.snapshot_filter_options

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.snapshot_filter_options
```
````

````{py:function} snapshot_output_options(func)
:canonical: archivebox.cli.archivebox_snapshot.snapshot_output_options

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.snapshot_output_options
```
````

````{py:function} build_snapshot_queryset(**kwargs) -> django.db.models.QuerySet
:canonical: archivebox.cli.archivebox_snapshot.build_snapshot_queryset

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.build_snapshot_queryset
```
````

````{py:function} list_snapshots(csv: str | None = None, as_json: bool = False, as_html: bool = False, with_headers: bool = False, **kwargs) -> int
:canonical: archivebox.cli.archivebox_snapshot.list_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.list_snapshots
```
````

````{py:function} update_snapshots(status: str | None = None, tag: str | None = None) -> int
:canonical: archivebox.cli.archivebox_snapshot.update_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.update_snapshots
```
````

````{py:function} delete_snapshots(yes: bool = False, dry_run: bool = False) -> int
:canonical: archivebox.cli.archivebox_snapshot.delete_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.delete_snapshots
```
````

````{py:function} main()
:canonical: archivebox.cli.archivebox_snapshot.main

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.main
```
````

````{py:function} create_cmd(urls: tuple, tag: str, status: str, depth: int)
:canonical: archivebox.cli.archivebox_snapshot.create_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.create_cmd
```
````

````{py:function} list_cmd(**kwargs)
:canonical: archivebox.cli.archivebox_snapshot.list_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.list_cmd
```
````

````{py:function} update_cmd(status: str | None, tag: str | None)
:canonical: archivebox.cli.archivebox_snapshot.update_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.update_cmd
```
````

````{py:function} delete_cmd(yes: bool, dry_run: bool)
:canonical: archivebox.cli.archivebox_snapshot.delete_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_snapshot.delete_cmd
```
````
