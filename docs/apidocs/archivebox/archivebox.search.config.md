# {py:mod}`archivebox.search.config`

```{py:module} archivebox.search.config
```

```{autodoc2-docstring} archivebox.search.config
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_default_search_mode <archivebox.search.config.get_default_search_mode>`
  - ```{autodoc2-docstring} archivebox.search.config.get_default_search_mode
    :summary:
    ```
* - {py:obj}`get_search_mode <archivebox.search.config.get_search_mode>`
  - ```{autodoc2-docstring} archivebox.search.config.get_search_mode
    :summary:
    ```
* - {py:obj}`get_search_mode_base <archivebox.search.config.get_search_mode_base>`
  - ```{autodoc2-docstring} archivebox.search.config.get_search_mode_base
    :summary:
    ```
* - {py:obj}`get_search_mode_backend <archivebox.search.config.get_search_mode_backend>`
  - ```{autodoc2-docstring} archivebox.search.config.get_search_mode_backend
    :summary:
    ```
* - {py:obj}`get_search_mode_options <archivebox.search.config.get_search_mode_options>`
  - ```{autodoc2-docstring} archivebox.search.config.get_search_mode_options
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SEARCH_MODES <archivebox.search.config.SEARCH_MODES>`
  - ```{autodoc2-docstring} archivebox.search.config.SEARCH_MODES
    :summary:
    ```
````

### API

````{py:data} SEARCH_MODES
:canonical: archivebox.search.config.SEARCH_MODES
:value: >
   ('meta', 'contents', 'deep')

```{autodoc2-docstring} archivebox.search.config.SEARCH_MODES
```

````

````{py:function} get_default_search_mode(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.search.config.get_default_search_mode

```{autodoc2-docstring} archivebox.search.config.get_default_search_mode
```
````

````{py:function} get_search_mode(search_mode: str | None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.search.config.get_search_mode

```{autodoc2-docstring} archivebox.search.config.get_search_mode
```
````

````{py:function} get_search_mode_base(search_mode: str | None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.search.config.get_search_mode_base

```{autodoc2-docstring} archivebox.search.config.get_search_mode_base
```
````

````{py:function} get_search_mode_backend(search_mode: str | None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str | None
:canonical: archivebox.search.config.get_search_mode_backend

```{autodoc2-docstring} archivebox.search.config.get_search_mode_backend
```
````

````{py:function} get_search_mode_options(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> list[dict[str, str]]
:canonical: archivebox.search.config.get_search_mode_options

```{autodoc2-docstring} archivebox.search.config.get_search_mode_options
```
````
