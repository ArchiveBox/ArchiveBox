# {py:mod}`archivebox.search.backends`

```{py:module} archivebox.search.backends
```

```{autodoc2-docstring} archivebox.search.backends
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`search_backend_env <archivebox.search.backends.search_backend_env>`
  - ```{autodoc2-docstring} archivebox.search.backends.search_backend_env
    :summary:
    ```
* - {py:obj}`normalize_search_backend_name <archivebox.search.backends.normalize_search_backend_name>`
  - ```{autodoc2-docstring} archivebox.search.backends.normalize_search_backend_name
    :summary:
    ```
* - {py:obj}`get_available_backends <archivebox.search.backends.get_available_backends>`
  - ```{autodoc2-docstring} archivebox.search.backends.get_available_backends
    :summary:
    ```
* - {py:obj}`get_backend <archivebox.search.backends.get_backend>`
  - ```{autodoc2-docstring} archivebox.search.backends.get_backend
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_search_backends_cache <archivebox.search.backends._search_backends_cache>`
  - ```{autodoc2-docstring} archivebox.search.backends._search_backends_cache
    :summary:
    ```
````

### API

````{py:data} _search_backends_cache
:canonical: archivebox.search.backends._search_backends_cache
:type: dict | None
:value: >
   None

```{autodoc2-docstring} archivebox.search.backends._search_backends_cache
```

````

````{py:function} search_backend_env(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any)
:canonical: archivebox.search.backends.search_backend_env

```{autodoc2-docstring} archivebox.search.backends.search_backend_env
```
````

````{py:function} normalize_search_backend_name(backend_name: str | None) -> str
:canonical: archivebox.search.backends.normalize_search_backend_name

```{autodoc2-docstring} archivebox.search.backends.normalize_search_backend_name
```
````

````{py:function} get_available_backends() -> dict
:canonical: archivebox.search.backends.get_available_backends

```{autodoc2-docstring} archivebox.search.backends.get_available_backends
```
````

````{py:function} get_backend(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> typing.Any
:canonical: archivebox.search.backends.get_backend

```{autodoc2-docstring} archivebox.search.backends.get_backend
```
````
