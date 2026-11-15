# {py:mod}`archivebox.cli.archivebox_install`

```{py:module} archivebox.cli.archivebox_install
```

```{autodoc2-docstring} archivebox.cli.archivebox_install
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_resolve_install_targets <archivebox.cli.archivebox_install._resolve_install_targets>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_install._resolve_install_targets
    :summary:
    ```
* - {py:obj}`_install_raw_binary_names <archivebox.cli.archivebox_install._install_raw_binary_names>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_install._install_raw_binary_names
    :summary:
    ```
* - {py:obj}`ensure_data_dir_lib_symlink <archivebox.cli.archivebox_install.ensure_data_dir_lib_symlink>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_install.ensure_data_dir_lib_symlink
    :summary:
    ```
* - {py:obj}`install <archivebox.cli.archivebox_install.install>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_install.install
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_install.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_install.main
    :summary:
    ```
````

### API

````{py:function} _resolve_install_targets(requested_names: tuple[str, ...]) -> tuple[list[str], list[str]]
:canonical: archivebox.cli.archivebox_install._resolve_install_targets

```{autodoc2-docstring} archivebox.cli.archivebox_install._resolve_install_targets
```
````

````{py:function} _install_raw_binary_names(binary_names: list[str], binproviders: str) -> None
:canonical: archivebox.cli.archivebox_install._install_raw_binary_names

```{autodoc2-docstring} archivebox.cli.archivebox_install._install_raw_binary_names
```
````

````{py:function} ensure_data_dir_lib_symlink(data_dir: pathlib.Path, abxpkg_lib_dir: pathlib.Path) -> pathlib.Path | None
:canonical: archivebox.cli.archivebox_install.ensure_data_dir_lib_symlink

```{autodoc2-docstring} archivebox.cli.archivebox_install.ensure_data_dir_lib_symlink
```
````

````{py:function} install(binaries: tuple[str, ...] = (), binproviders: str = '*', dry_run: bool = False) -> None
:canonical: archivebox.cli.archivebox_install.install

```{autodoc2-docstring} archivebox.cli.archivebox_install.install
```
````

````{py:function} main(**kwargs) -> None
:canonical: archivebox.cli.archivebox_install.main

```{autodoc2-docstring} archivebox.cli.archivebox_install.main
```
````
