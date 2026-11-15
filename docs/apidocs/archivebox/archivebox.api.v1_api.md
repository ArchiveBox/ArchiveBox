# {py:mod}`archivebox.api.v1_api`

```{py:module} archivebox.api.v1_api
```

```{autodoc2-docstring} archivebox.api.v1_api
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`NinjaAPIWithIOCapture <archivebox.api.v1_api.NinjaAPIWithIOCapture>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.NinjaAPIWithIOCapture
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_urls <archivebox.api.v1_api.register_urls>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.register_urls
    :summary:
    ```
* - {py:obj}`generic_exception_handler <archivebox.api.v1_api.generic_exception_handler>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.generic_exception_handler
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`COMMIT_HASH <archivebox.api.v1_api.COMMIT_HASH>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.COMMIT_HASH
    :summary:
    ```
* - {py:obj}`html_description <archivebox.api.v1_api.html_description>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.html_description
    :summary:
    ```
* - {py:obj}`api <archivebox.api.v1_api.api>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.api
    :summary:
    ```
* - {py:obj}`urls <archivebox.api.v1_api.urls>`
  - ```{autodoc2-docstring} archivebox.api.v1_api.urls
    :summary:
    ```
````

### API

````{py:data} COMMIT_HASH
:canonical: archivebox.api.v1_api.COMMIT_HASH
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_api.COMMIT_HASH
```

````

````{py:data} html_description
:canonical: archivebox.api.v1_api.html_description
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_api.html_description
```

````

````{py:function} register_urls(api: ninja.NinjaAPI) -> ninja.NinjaAPI
:canonical: archivebox.api.v1_api.register_urls

```{autodoc2-docstring} archivebox.api.v1_api.register_urls
```
````

`````{py:class} NinjaAPIWithIOCapture
:canonical: archivebox.api.v1_api.NinjaAPIWithIOCapture

Bases: {py:obj}`ninja.NinjaAPI`

```{autodoc2-docstring} archivebox.api.v1_api.NinjaAPIWithIOCapture
```

````{py:method} get_openapi_schema(*, path_prefix: str | None = None, path_params: dict[str, typing.Any] | None = None) -> ninja.openapi.schema.OpenAPISchema
:canonical: archivebox.api.v1_api.NinjaAPIWithIOCapture.get_openapi_schema

```{autodoc2-docstring} archivebox.api.v1_api.NinjaAPIWithIOCapture.get_openapi_schema
```

````

````{py:method} _schema_for_prefix(path_prefix: str) -> ninja.openapi.schema.OpenAPISchema
:canonical: archivebox.api.v1_api.NinjaAPIWithIOCapture._schema_for_prefix

```{autodoc2-docstring} archivebox.api.v1_api.NinjaAPIWithIOCapture._schema_for_prefix
```

````

````{py:method} create_temporal_response(request: django.http.HttpRequest) -> django.http.HttpResponse
:canonical: archivebox.api.v1_api.NinjaAPIWithIOCapture.create_temporal_response

```{autodoc2-docstring} archivebox.api.v1_api.NinjaAPIWithIOCapture.create_temporal_response
```

````

`````

````{py:data} api
:canonical: archivebox.api.v1_api.api
:value: >
   'NinjaAPIWithIOCapture(...)'

```{autodoc2-docstring} archivebox.api.v1_api.api
```

````

````{py:data} urls
:canonical: archivebox.api.v1_api.urls
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_api.urls
```

````

````{py:function} generic_exception_handler(request, err)
:canonical: archivebox.api.v1_api.generic_exception_handler

```{autodoc2-docstring} archivebox.api.v1_api.generic_exception_handler
```
````
