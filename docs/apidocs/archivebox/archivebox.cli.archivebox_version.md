# {py:mod}`archivebox.cli.archivebox_version`

```{py:module} archivebox.cli.archivebox_version
```

```{autodoc2-docstring} archivebox.cli.archivebox_version
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_format_binary_abspath <archivebox.cli.archivebox_version._format_binary_abspath>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_version._format_binary_abspath
    :summary:
    ```
* - {py:obj}`_render_binary_abspath <archivebox.cli.archivebox_version._render_binary_abspath>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_version._render_binary_abspath
    :summary:
    ```
* - {py:obj}`_binary_row_dedupe_key <archivebox.cli.archivebox_version._binary_row_dedupe_key>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_version._binary_row_dedupe_key
    :summary:
    ```
* - {py:obj}`version <archivebox.cli.archivebox_version.version>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_version.version
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_version.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_version.main
    :summary:
    ```
````

### API

````{py:function} _format_binary_abspath(abspath: str, *, pwd: pathlib.Path, lib_dir: pathlib.Path, personas_dir: pathlib.Path, home: pathlib.Path) -> str
:canonical: archivebox.cli.archivebox_version._format_binary_abspath

```{autodoc2-docstring} archivebox.cli.archivebox_version._format_binary_abspath
```
````

````{py:function} _render_binary_abspath(abspath: str)
:canonical: archivebox.cli.archivebox_version._render_binary_abspath

```{autodoc2-docstring} archivebox.cli.archivebox_version._render_binary_abspath
```
````

````{py:function} _binary_row_dedupe_key(*, display_name: str, valid: bool, version: str, provider: str, abspath: str) -> tuple[str, str, str, str]
:canonical: archivebox.cli.archivebox_version._binary_row_dedupe_key

```{autodoc2-docstring} archivebox.cli.archivebox_version._binary_row_dedupe_key
```
````

````{py:function} version(quiet: bool = False, binaries: collections.abc.Iterable[str] = (), no_cache: bool = False) -> list[str]
:canonical: archivebox.cli.archivebox_version.version

```{autodoc2-docstring} archivebox.cli.archivebox_version.version
```
````

````{py:function} main(**kwargs)
:canonical: archivebox.cli.archivebox_version.main

```{autodoc2-docstring} archivebox.cli.archivebox_version.main
```
````
