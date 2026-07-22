# {py:mod}`archivebox.cli.archivebox_remove`

```{py:module} archivebox.cli.archivebox_remove
```

```{autodoc2-docstring} archivebox.cli.archivebox_remove
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`remove <archivebox.cli.archivebox_remove.remove>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_remove.remove
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_remove.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_remove.main
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_remove.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_remove.__command__
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_remove.__command__
:value: >
   'archivebox remove'

```{autodoc2-docstring} archivebox.cli.archivebox_remove.__command__
```

````

````{py:function} remove(filter_patterns: collections.abc.Iterable[str] = (), filter_type: str = 'exact', snapshots: django.db.models.QuerySet | None = None, after: float | None = None, before: float | None = None, yes: bool = False, delete: bool = False, out_dir: pathlib.Path = CONSTANTS.DATA_DIR, timeout: float | None = None, **kwargs) -> dict[str, object]
:canonical: archivebox.cli.archivebox_remove.remove

```{autodoc2-docstring} archivebox.cli.archivebox_remove.remove
```
````

````{py:function} main(**kwargs)
:canonical: archivebox.cli.archivebox_remove.main

```{autodoc2-docstring} archivebox.cli.archivebox_remove.main
```
````
