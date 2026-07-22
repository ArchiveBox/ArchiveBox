# {py:mod}`archivebox.api.auth`

```{py:module} archivebox.api.auth
```

```{autodoc2-docstring} archivebox.api.auth
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`HeaderTokenAuth <archivebox.api.auth.HeaderTokenAuth>`
  - ```{autodoc2-docstring} archivebox.api.auth.HeaderTokenAuth
    :summary:
    ```
* - {py:obj}`BearerTokenAuth <archivebox.api.auth.BearerTokenAuth>`
  - ```{autodoc2-docstring} archivebox.api.auth.BearerTokenAuth
    :summary:
    ```
* - {py:obj}`QueryParamTokenAuth <archivebox.api.auth.QueryParamTokenAuth>`
  - ```{autodoc2-docstring} archivebox.api.auth.QueryParamTokenAuth
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_or_create_api_token <archivebox.api.auth.get_or_create_api_token>`
  - ```{autodoc2-docstring} archivebox.api.auth.get_or_create_api_token
    :summary:
    ```
* - {py:obj}`auth_using_token <archivebox.api.auth.auth_using_token>`
  - ```{autodoc2-docstring} archivebox.api.auth.auth_using_token
    :summary:
    ```
* - {py:obj}`token_from_request <archivebox.api.auth.token_from_request>`
  - ```{autodoc2-docstring} archivebox.api.auth.token_from_request
    :summary:
    ```
* - {py:obj}`authenticated_user_from_request <archivebox.api.auth.authenticated_user_from_request>`
  - ```{autodoc2-docstring} archivebox.api.auth.authenticated_user_from_request
    :summary:
    ```
* - {py:obj}`auth_using_password <archivebox.api.auth.auth_using_password>`
  - ```{autodoc2-docstring} archivebox.api.auth.auth_using_password
    :summary:
    ```
* - {py:obj}`_require_superuser <archivebox.api.auth._require_superuser>`
  - ```{autodoc2-docstring} archivebox.api.auth._require_superuser
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`API_AUTH_METHODS <archivebox.api.auth.API_AUTH_METHODS>`
  - ```{autodoc2-docstring} archivebox.api.auth.API_AUTH_METHODS
    :summary:
    ```
````

### API

````{py:function} get_or_create_api_token(user: django.contrib.auth.models.User | None)
:canonical: archivebox.api.auth.get_or_create_api_token

```{autodoc2-docstring} archivebox.api.auth.get_or_create_api_token
```
````

````{py:function} auth_using_token(token: str | None, request: django.http.HttpRequest | None = None) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.auth_using_token

```{autodoc2-docstring} archivebox.api.auth.auth_using_token
```
````

````{py:function} token_from_request(request: django.http.HttpRequest) -> str
:canonical: archivebox.api.auth.token_from_request

```{autodoc2-docstring} archivebox.api.auth.token_from_request
```
````

````{py:function} authenticated_user_from_request(request: django.http.HttpRequest) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.authenticated_user_from_request

```{autodoc2-docstring} archivebox.api.auth.authenticated_user_from_request
```
````

````{py:function} auth_using_password(username: str | None, password: str | None, request: django.http.HttpRequest | None = None) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.auth_using_password

```{autodoc2-docstring} archivebox.api.auth.auth_using_password
```
````

````{py:function} _require_superuser(user: django.contrib.auth.models.User | None, request: django.http.HttpRequest, auth_method: str) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth._require_superuser

```{autodoc2-docstring} archivebox.api.auth._require_superuser
```
````

`````{py:class} HeaderTokenAuth()
:canonical: archivebox.api.auth.HeaderTokenAuth

Bases: {py:obj}`ninja.security.APIKeyHeader`

```{autodoc2-docstring} archivebox.api.auth.HeaderTokenAuth
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.auth.HeaderTokenAuth.__init__
```

````{py:attribute} param_name
:canonical: archivebox.api.auth.HeaderTokenAuth.param_name
:value: >
   'X-ArchiveBox-API-Key'

```{autodoc2-docstring} archivebox.api.auth.HeaderTokenAuth.param_name
```

````

````{py:method} authenticate(request: django.http.HttpRequest, key: str | None) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.HeaderTokenAuth.authenticate

```{autodoc2-docstring} archivebox.api.auth.HeaderTokenAuth.authenticate
```

````

`````

`````{py:class} BearerTokenAuth()
:canonical: archivebox.api.auth.BearerTokenAuth

Bases: {py:obj}`ninja.security.HttpBearer`

```{autodoc2-docstring} archivebox.api.auth.BearerTokenAuth
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.auth.BearerTokenAuth.__init__
```

````{py:method} authenticate(request: django.http.HttpRequest, token: str) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.BearerTokenAuth.authenticate

```{autodoc2-docstring} archivebox.api.auth.BearerTokenAuth.authenticate
```

````

`````

`````{py:class} QueryParamTokenAuth()
:canonical: archivebox.api.auth.QueryParamTokenAuth

Bases: {py:obj}`ninja.security.APIKeyQuery`

```{autodoc2-docstring} archivebox.api.auth.QueryParamTokenAuth
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.auth.QueryParamTokenAuth.__init__
```

````{py:attribute} param_name
:canonical: archivebox.api.auth.QueryParamTokenAuth.param_name
:value: >
   'api_key'

```{autodoc2-docstring} archivebox.api.auth.QueryParamTokenAuth.param_name
```

````

````{py:method} authenticate(request: django.http.HttpRequest, key: str | None) -> django.contrib.auth.models.User | None
:canonical: archivebox.api.auth.QueryParamTokenAuth.authenticate

```{autodoc2-docstring} archivebox.api.auth.QueryParamTokenAuth.authenticate
```

````

`````

````{py:data} API_AUTH_METHODS
:canonical: archivebox.api.auth.API_AUTH_METHODS
:value: >
   None

```{autodoc2-docstring} archivebox.api.auth.API_AUTH_METHODS
```

````
