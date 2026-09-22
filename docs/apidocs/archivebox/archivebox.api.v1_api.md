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
  -
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

`````{py:class} NinjaAPIWithIOCapture(*, title: str = 'NinjaAPI', version: str = '1.0.0', description: str = '', openapi_url: typing.Optional[str] = '/openapi.json', docs: ninja.openapi.docs.DocsBase = Swagger(), docs_url: typing.Optional[str] = '/docs', docs_decorator: typing.Optional[typing.Callable[[ninja.types.TCallable], ninja.types.TCallable]] = None, servers: typing.Optional[typing.List[ninja.types.DictStrAny]] = None, urls_namespace: typing.Optional[str] = None, auth: typing.Optional[typing.Union[typing.Sequence[typing.Callable], typing.Callable, ninja.constants.NOT_SET_TYPE]] = NOT_SET, throttle: typing.Union[ninja.throttling.BaseThrottle, typing.List[ninja.throttling.BaseThrottle], ninja.constants.NOT_SET_TYPE] = NOT_SET, renderer: typing.Optional[ninja.renderers.BaseRenderer] = None, parser: typing.Optional[ninja.parser.Parser] = None, default_router: typing.Optional[ninja.router.Router] = None, openapi_extra: typing.Optional[typing.Dict[str, typing.Any]] = None)
:canonical: archivebox.api.v1_api.NinjaAPIWithIOCapture

Bases: {py:obj}`ninja.NinjaAPI`

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
