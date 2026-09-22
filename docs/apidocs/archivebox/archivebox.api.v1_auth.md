# {py:mod}`archivebox.api.v1_auth`

```{py:module} archivebox.api.v1_auth
```

```{autodoc2-docstring} archivebox.api.v1_auth
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PasswordAuthSchema <archivebox.api.v1_auth.PasswordAuthSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_auth.PasswordAuthSchema
    :summary:
    ```
* - {py:obj}`TokenAuthSchema <archivebox.api.v1_auth.TokenAuthSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_auth.TokenAuthSchema
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_api_token <archivebox.api.v1_auth.get_api_token>`
  - ```{autodoc2-docstring} archivebox.api.v1_auth.get_api_token
    :summary:
    ```
* - {py:obj}`check_api_token <archivebox.api.v1_auth.check_api_token>`
  - ```{autodoc2-docstring} archivebox.api.v1_auth.check_api_token
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_auth.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_auth.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_auth.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_auth.router
```

````

`````{py:class} PasswordAuthSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_auth.PasswordAuthSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_auth.PasswordAuthSchema
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.v1_auth.PasswordAuthSchema.__init__
```

````{py:attribute} username
:canonical: archivebox.api.v1_auth.PasswordAuthSchema.username
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_auth.PasswordAuthSchema.username
```

````

````{py:attribute} password
:canonical: archivebox.api.v1_auth.PasswordAuthSchema.password
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_auth.PasswordAuthSchema.password
```

````

`````

````{py:function} get_api_token(request: django.http.HttpRequest, auth_data: archivebox.api.v1_auth.PasswordAuthSchema)
:canonical: archivebox.api.v1_auth.get_api_token

```{autodoc2-docstring} archivebox.api.v1_auth.get_api_token
```
````

`````{py:class} TokenAuthSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_auth.TokenAuthSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_auth.TokenAuthSchema
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.v1_auth.TokenAuthSchema.__init__
```

````{py:attribute} token
:canonical: archivebox.api.v1_auth.TokenAuthSchema.token
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_auth.TokenAuthSchema.token
```

````

`````

````{py:function} check_api_token(request: django.http.HttpRequest, token_data: archivebox.api.v1_auth.TokenAuthSchema)
:canonical: archivebox.api.v1_auth.check_api_token

```{autodoc2-docstring} archivebox.api.v1_auth.check_api_token
```
````
