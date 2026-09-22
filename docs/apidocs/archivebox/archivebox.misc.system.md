# {py:mod}`archivebox.misc.system`

```{py:module} archivebox.misc.system
```

```{autodoc2-docstring} archivebox.misc.system
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`atomic_write <archivebox.misc.system.atomic_write>`
  - ```{autodoc2-docstring} archivebox.misc.system.atomic_write
    :summary:
    ```
* - {py:obj}`get_dir_size <archivebox.misc.system.get_dir_size>`
  - ```{autodoc2-docstring} archivebox.misc.system.get_dir_size
    :summary:
    ```
````

### API

````{py:function} atomic_write(path: pathlib.Path | str, contents: dict | str | bytes, overwrite: bool = True, config=None, **config_kwargs) -> None
:canonical: archivebox.misc.system.atomic_write

```{autodoc2-docstring} archivebox.misc.system.atomic_write
```
````

````{py:function} get_dir_size(path: str | pathlib.Path, recursive: bool = True, pattern: str | None = None) -> tuple[int, int, int]
:canonical: archivebox.misc.system.get_dir_size

```{autodoc2-docstring} archivebox.misc.system.get_dir_size
```
````
