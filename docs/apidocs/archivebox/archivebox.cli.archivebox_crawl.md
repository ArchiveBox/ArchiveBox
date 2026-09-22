# {py:mod}`archivebox.cli.archivebox_crawl`

```{py:module} archivebox.cli.archivebox_crawl
```

```{autodoc2-docstring} archivebox.cli.archivebox_crawl
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`create_crawl <archivebox.cli.archivebox_crawl.create_crawl>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.create_crawl
    :summary:
    ```
* - {py:obj}`list_crawls <archivebox.cli.archivebox_crawl.list_crawls>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.list_crawls
    :summary:
    ```
* - {py:obj}`update_crawls <archivebox.cli.archivebox_crawl.update_crawls>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.update_crawls
    :summary:
    ```
* - {py:obj}`delete_crawls <archivebox.cli.archivebox_crawl.delete_crawls>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.delete_crawls
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_crawl.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.main
    :summary:
    ```
* - {py:obj}`create_cmd <archivebox.cli.archivebox_crawl.create_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.create_cmd
    :summary:
    ```
* - {py:obj}`list_cmd <archivebox.cli.archivebox_crawl.list_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.list_cmd
    :summary:
    ```
* - {py:obj}`update_cmd <archivebox.cli.archivebox_crawl.update_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.update_cmd
    :summary:
    ```
* - {py:obj}`delete_cmd <archivebox.cli.archivebox_crawl.delete_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.delete_cmd
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_crawl.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_crawl.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_crawl.__command__
:value: >
   'archivebox crawl'

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.__command__
```

````

````{py:function} create_crawl(urls: collections.abc.Iterable[str], depth: int = 0, tag: str = '', status: str = 'queued', created_by_id: int | None = None) -> int
:canonical: archivebox.cli.archivebox_crawl.create_crawl

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.create_crawl
```
````

````{py:function} list_crawls(status: str | None = None, urls__icontains: str | None = None, max_depth: int | None = None, limit: int | None = None) -> int
:canonical: archivebox.cli.archivebox_crawl.list_crawls

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.list_crawls
```
````

````{py:function} update_crawls(status: str | None = None, max_depth: int | None = None) -> int
:canonical: archivebox.cli.archivebox_crawl.update_crawls

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.update_crawls
```
````

````{py:function} delete_crawls(yes: bool = False, dry_run: bool = False) -> int
:canonical: archivebox.cli.archivebox_crawl.delete_crawls

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.delete_crawls
```
````

````{py:function} main()
:canonical: archivebox.cli.archivebox_crawl.main

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.main
```
````

````{py:function} create_cmd(urls: tuple, depth: int, tag: str, status: str)
:canonical: archivebox.cli.archivebox_crawl.create_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.create_cmd
```
````

````{py:function} list_cmd(status: str | None, urls__icontains: str | None, max_depth: int | None, limit: int | None)
:canonical: archivebox.cli.archivebox_crawl.list_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.list_cmd
```
````

````{py:function} update_cmd(status: str | None, max_depth: int | None)
:canonical: archivebox.cli.archivebox_crawl.update_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.update_cmd
```
````

````{py:function} delete_cmd(yes: bool, dry_run: bool)
:canonical: archivebox.cli.archivebox_crawl.delete_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_crawl.delete_cmd
```
````
