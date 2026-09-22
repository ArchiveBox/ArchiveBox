# {py:mod}`archivebox.misc.hashing`

```{py:module} archivebox.misc.hashing
```

```{autodoc2-docstring} archivebox.misc.hashing
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_cached_file_hash <archivebox.misc.hashing._cached_file_hash>`
  - ```{autodoc2-docstring} archivebox.misc.hashing._cached_file_hash
    :summary:
    ```
* - {py:obj}`hash_file <archivebox.misc.hashing.hash_file>`
  - ```{autodoc2-docstring} archivebox.misc.hashing.hash_file
    :summary:
    ```
* - {py:obj}`get_dir_hashes <archivebox.misc.hashing.get_dir_hashes>`
  - ```{autodoc2-docstring} archivebox.misc.hashing.get_dir_hashes
    :summary:
    ```
* - {py:obj}`get_dir_entries <archivebox.misc.hashing.get_dir_entries>`
  - ```{autodoc2-docstring} archivebox.misc.hashing.get_dir_entries
    :summary:
    ```
* - {py:obj}`get_dir_sizes <archivebox.misc.hashing.get_dir_sizes>`
  - ```{autodoc2-docstring} archivebox.misc.hashing.get_dir_sizes
    :summary:
    ```
* - {py:obj}`get_dir_info <archivebox.misc.hashing.get_dir_info>`
  - ```{autodoc2-docstring} archivebox.misc.hashing.get_dir_info
    :summary:
    ```
````

### API

````{py:function} _cached_file_hash(filepath: str, size: int, mtime: float) -> str
:canonical: archivebox.misc.hashing._cached_file_hash

```{autodoc2-docstring} archivebox.misc.hashing._cached_file_hash
```
````

````{py:function} hash_file(file_path: pathlib.Path, pwd: pathlib.Path | None = None) -> str
:canonical: archivebox.misc.hashing.hash_file

```{autodoc2-docstring} archivebox.misc.hashing.hash_file
```
````

````{py:function} get_dir_hashes(dir_path: pathlib.Path, pwd: pathlib.Path | None = None, filter_func: collections.abc.Callable | None = None, max_depth: int = -1) -> dict[str, str]
:canonical: archivebox.misc.hashing.get_dir_hashes

```{autodoc2-docstring} archivebox.misc.hashing.get_dir_hashes
```
````

````{py:function} get_dir_entries(dir_path: pathlib.Path, pwd: pathlib.Path | None = None, recursive: bool = True, include_files: bool = True, include_dirs: bool = True, include_hidden: bool = False, filter_func: collections.abc.Callable | None = None, max_depth: int = -1) -> tuple[str, ...]
:canonical: archivebox.misc.hashing.get_dir_entries

```{autodoc2-docstring} archivebox.misc.hashing.get_dir_entries
```
````

````{py:function} get_dir_sizes(dir_path: pathlib.Path, pwd: pathlib.Path | None = None, **kwargs) -> dict[str, int]
:canonical: archivebox.misc.hashing.get_dir_sizes

```{autodoc2-docstring} archivebox.misc.hashing.get_dir_sizes
```
````

````{py:function} get_dir_info(dir_path: pathlib.Path, pwd: pathlib.Path | None = None, filter_func: collections.abc.Callable | None = None, max_depth: int = -1) -> dict
:canonical: archivebox.misc.hashing.get_dir_info

```{autodoc2-docstring} archivebox.misc.hashing.get_dir_info
```
````
