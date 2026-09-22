# {py:mod}`archivebox.cli.archivebox_archiveresult`

```{py:module} archivebox.cli.archivebox_archiveresult
```

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_archiveresult_request <archivebox.cli.archivebox_archiveresult.build_archiveresult_request>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.build_archiveresult_request
    :summary:
    ```
* - {py:obj}`create_archiveresults <archivebox.cli.archivebox_archiveresult.create_archiveresults>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.create_archiveresults
    :summary:
    ```
* - {py:obj}`list_archiveresults <archivebox.cli.archivebox_archiveresult.list_archiveresults>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.list_archiveresults
    :summary:
    ```
* - {py:obj}`update_archiveresults <archivebox.cli.archivebox_archiveresult.update_archiveresults>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.update_archiveresults
    :summary:
    ```
* - {py:obj}`delete_archiveresults <archivebox.cli.archivebox_archiveresult.delete_archiveresults>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.delete_archiveresults
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_archiveresult.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.main
    :summary:
    ```
* - {py:obj}`create_cmd <archivebox.cli.archivebox_archiveresult.create_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.create_cmd
    :summary:
    ```
* - {py:obj}`list_cmd <archivebox.cli.archivebox_archiveresult.list_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.list_cmd
    :summary:
    ```
* - {py:obj}`update_cmd <archivebox.cli.archivebox_archiveresult.update_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.update_cmd
    :summary:
    ```
* - {py:obj}`delete_cmd <archivebox.cli.archivebox_archiveresult.delete_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.delete_cmd
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_archiveresult.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_archiveresult.__command__
:value: >
   'archivebox archiveresult'

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.__command__
```

````

````{py:function} build_archiveresult_request(snapshot_id: str, plugin: str, hook_name: str = '', status: str = 'queued') -> dict
:canonical: archivebox.cli.archivebox_archiveresult.build_archiveresult_request

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.build_archiveresult_request
```
````

````{py:function} create_archiveresults(snapshot_id: str | None = None, plugin: str | None = None, status: str = 'queued') -> int
:canonical: archivebox.cli.archivebox_archiveresult.create_archiveresults

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.create_archiveresults
```
````

````{py:function} list_archiveresults(status: str | None = None, plugin: str | None = None, snapshot_id: str | None = None, limit: int | None = None) -> int
:canonical: archivebox.cli.archivebox_archiveresult.list_archiveresults

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.list_archiveresults
```
````

````{py:function} update_archiveresults(status: str | None = None) -> int
:canonical: archivebox.cli.archivebox_archiveresult.update_archiveresults

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.update_archiveresults
```
````

````{py:function} delete_archiveresults(yes: bool = False, dry_run: bool = False) -> int
:canonical: archivebox.cli.archivebox_archiveresult.delete_archiveresults

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.delete_archiveresults
```
````

````{py:function} main()
:canonical: archivebox.cli.archivebox_archiveresult.main

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.main
```
````

````{py:function} create_cmd(snapshot_id: str | None, plugin: str | None, status: str)
:canonical: archivebox.cli.archivebox_archiveresult.create_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.create_cmd
```
````

````{py:function} list_cmd(status: str | None, plugin: str | None, snapshot_id: str | None, limit: int | None)
:canonical: archivebox.cli.archivebox_archiveresult.list_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.list_cmd
```
````

````{py:function} update_cmd(status: str | None)
:canonical: archivebox.cli.archivebox_archiveresult.update_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.update_cmd
```
````

````{py:function} delete_cmd(yes: bool, dry_run: bool)
:canonical: archivebox.cli.archivebox_archiveresult.delete_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_archiveresult.delete_cmd
```
````
