# {py:mod}`archivebox.cli.archivebox_add`

```{py:module} archivebox.cli.archivebox_add
```

```{autodoc2-docstring} archivebox.cli.archivebox_add
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_collect_input_urls <archivebox.cli.archivebox_add._collect_input_urls>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_add._collect_input_urls
    :summary:
    ```
* - {py:obj}`add <archivebox.cli.archivebox_add.add>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_add.add
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_add.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_add.main
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_add.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_add.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_add.__command__
:value: >
   'archivebox add'

```{autodoc2-docstring} archivebox.cli.archivebox_add.__command__
```

````

````{py:function} _collect_input_urls(args: tuple[str, ...], *, parser: str = 'auto') -> list[str]
:canonical: archivebox.cli.archivebox_add._collect_input_urls

```{autodoc2-docstring} archivebox.cli.archivebox_add._collect_input_urls
```
````

````{py:function} add(urls: str | list[str], snapshot_ids: list[str] | None = None, depth: int | str = 0, max_urls: int = 0, crawl_max_size: int | str = 0, crawl_timeout: int = 0, snapshot_max_size: int | str = 0, crawl_max_concurrent_snapshots: int | None = None, tag: str = '', url_allowlist: str = '', url_denylist: str = '', parser: str = 'auto', plugins: str = '', persona: str = 'Default', index_only: bool = False, bg: bool = False, created_by_id: int | None = None, config: dict[str, typing.Any] | None = None) -> tuple[archivebox.crawls.models.Crawl, django.db.models.QuerySet[archivebox.core.models.Snapshot]]
:canonical: archivebox.cli.archivebox_add.add

```{autodoc2-docstring} archivebox.cli.archivebox_add.add
```
````

````{py:function} main(**kwargs)
:canonical: archivebox.cli.archivebox_add.main

```{autodoc2-docstring} archivebox.cli.archivebox_add.main
```
````
