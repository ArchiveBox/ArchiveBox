# {py:mod}`archivebox.cli.archivebox_binary`

```{py:module} archivebox.cli.archivebox_binary
```

```{autodoc2-docstring} archivebox.cli.archivebox_binary
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`create_binary <archivebox.cli.archivebox_binary.create_binary>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.create_binary
    :summary:
    ```
* - {py:obj}`list_binaries <archivebox.cli.archivebox_binary.list_binaries>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.list_binaries
    :summary:
    ```
* - {py:obj}`update_binaries <archivebox.cli.archivebox_binary.update_binaries>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.update_binaries
    :summary:
    ```
* - {py:obj}`delete_binaries <archivebox.cli.archivebox_binary.delete_binaries>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.delete_binaries
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_binary.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.main
    :summary:
    ```
* - {py:obj}`create_cmd <archivebox.cli.archivebox_binary.create_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.create_cmd
    :summary:
    ```
* - {py:obj}`list_cmd <archivebox.cli.archivebox_binary.list_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.list_cmd
    :summary:
    ```
* - {py:obj}`update_cmd <archivebox.cli.archivebox_binary.update_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.update_cmd
    :summary:
    ```
* - {py:obj}`delete_cmd <archivebox.cli.archivebox_binary.delete_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.delete_cmd
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_binary.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_binary.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_binary.__command__
:value: >
   'archivebox binary'

```{autodoc2-docstring} archivebox.cli.archivebox_binary.__command__
```

````

````{py:function} create_binary(name: str, abspath: str, version: str = '') -> int
:canonical: archivebox.cli.archivebox_binary.create_binary

```{autodoc2-docstring} archivebox.cli.archivebox_binary.create_binary
```
````

````{py:function} list_binaries(name: str | None = None, abspath__icontains: str | None = None, version__icontains: str | None = None, limit: int | None = None) -> int
:canonical: archivebox.cli.archivebox_binary.list_binaries

```{autodoc2-docstring} archivebox.cli.archivebox_binary.list_binaries
```
````

````{py:function} update_binaries(version: str | None = None, abspath: str | None = None) -> int
:canonical: archivebox.cli.archivebox_binary.update_binaries

```{autodoc2-docstring} archivebox.cli.archivebox_binary.update_binaries
```
````

````{py:function} delete_binaries(yes: bool = False, dry_run: bool = False) -> int
:canonical: archivebox.cli.archivebox_binary.delete_binaries

```{autodoc2-docstring} archivebox.cli.archivebox_binary.delete_binaries
```
````

````{py:function} main()
:canonical: archivebox.cli.archivebox_binary.main

```{autodoc2-docstring} archivebox.cli.archivebox_binary.main
```
````

````{py:function} create_cmd(name: str, abspath: str, version: str)
:canonical: archivebox.cli.archivebox_binary.create_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_binary.create_cmd
```
````

````{py:function} list_cmd(name: str | None, abspath__icontains: str | None, version__icontains: str | None, limit: int | None)
:canonical: archivebox.cli.archivebox_binary.list_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_binary.list_cmd
```
````

````{py:function} update_cmd(version: str | None, abspath: str | None)
:canonical: archivebox.cli.archivebox_binary.update_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_binary.update_cmd
```
````

````{py:function} delete_cmd(yes: bool, dry_run: bool)
:canonical: archivebox.cli.archivebox_binary.delete_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_binary.delete_cmd
```
````
