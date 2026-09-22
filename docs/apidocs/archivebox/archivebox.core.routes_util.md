# {py:mod}`archivebox.core.routes_util`

```{py:module} archivebox.core.routes_util
```

```{autodoc2-docstring} archivebox.core.routes_util
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`split_host_port <archivebox.core.routes_util.split_host_port>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.split_host_port
    :summary:
    ```
* - {py:obj}`_normalize_base_url <archivebox.core.routes_util._normalize_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._normalize_base_url
    :summary:
    ```
* - {py:obj}`normalize_base_url <archivebox.core.routes_util.normalize_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.normalize_base_url
    :summary:
    ```
* - {py:obj}`_csrf_trusted_origins <archivebox.core.routes_util._csrf_trusted_origins>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._csrf_trusted_origins
    :summary:
    ```
* - {py:obj}`_allowed_hosts <archivebox.core.routes_util._allowed_hosts>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._allowed_hosts
    :summary:
    ```
* - {py:obj}`derive_base_url_from_csrf <archivebox.core.routes_util.derive_base_url_from_csrf>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.derive_base_url_from_csrf
    :summary:
    ```
* - {py:obj}`get_listen_host <archivebox.core.routes_util.get_listen_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_listen_host
    :summary:
    ```
* - {py:obj}`get_listen_parts <archivebox.core.routes_util.get_listen_parts>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_listen_parts
    :summary:
    ```
* - {py:obj}`_with_port <archivebox.core.routes_util._with_port>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._with_port
    :summary:
    ```
* - {py:obj}`strip_role_subdomain <archivebox.core.routes_util.strip_role_subdomain>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.strip_role_subdomain
    :summary:
    ```
* - {py:obj}`_is_local_bind_host <archivebox.core.routes_util._is_local_bind_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._is_local_bind_host
    :summary:
    ```
* - {py:obj}`canonical_base_host_for_request <archivebox.core.routes_util.canonical_base_host_for_request>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.canonical_base_host_for_request
    :summary:
    ```
* - {py:obj}`_root_host_from_listen <archivebox.core.routes_util._root_host_from_listen>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._root_host_from_listen
    :summary:
    ```
* - {py:obj}`get_base_url <archivebox.core.routes_util.get_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_base_url
    :summary:
    ```
* - {py:obj}`get_base_host <archivebox.core.routes_util.get_base_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_base_host
    :summary:
    ```
* - {py:obj}`_build_base_host <archivebox.core.routes_util._build_base_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._build_base_host
    :summary:
    ```
* - {py:obj}`get_admin_host <archivebox.core.routes_util.get_admin_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_admin_host
    :summary:
    ```
* - {py:obj}`get_web_host <archivebox.core.routes_util.get_web_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_web_host
    :summary:
    ```
* - {py:obj}`get_api_host <archivebox.core.routes_util.get_api_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_api_host
    :summary:
    ```
* - {py:obj}`get_snapshot_subdomain <archivebox.core.routes_util.get_snapshot_subdomain>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_subdomain
    :summary:
    ```
* - {py:obj}`get_snapshot_host <archivebox.core.routes_util.get_snapshot_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_host
    :summary:
    ```
* - {py:obj}`get_original_host <archivebox.core.routes_util.get_original_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_original_host
    :summary:
    ```
* - {py:obj}`is_snapshot_subdomain <archivebox.core.routes_util.is_snapshot_subdomain>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.is_snapshot_subdomain
    :summary:
    ```
* - {py:obj}`get_snapshot_lookup_key <archivebox.core.routes_util.get_snapshot_lookup_key>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_lookup_key
    :summary:
    ```
* - {py:obj}`get_listen_subdomain <archivebox.core.routes_util.get_listen_subdomain>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_listen_subdomain
    :summary:
    ```
* - {py:obj}`host_matches <archivebox.core.routes_util.host_matches>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.host_matches
    :summary:
    ```
* - {py:obj}`is_allowed_archivebox_redirect_url <archivebox.core.routes_util.is_allowed_archivebox_redirect_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.is_allowed_archivebox_redirect_url
    :summary:
    ```
* - {py:obj}`_scheme_from_request <archivebox.core.routes_util._scheme_from_request>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._scheme_from_request
    :summary:
    ```
* - {py:obj}`_build_base_url_for_host <archivebox.core.routes_util._build_base_url_for_host>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._build_base_url_for_host
    :summary:
    ```
* - {py:obj}`get_admin_base_url <archivebox.core.routes_util.get_admin_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_admin_base_url
    :summary:
    ```
* - {py:obj}`get_web_base_url <archivebox.core.routes_util.get_web_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_web_base_url
    :summary:
    ```
* - {py:obj}`get_api_base_url <archivebox.core.routes_util.get_api_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_api_base_url
    :summary:
    ```
* - {py:obj}`get_snapshot_base_url <archivebox.core.routes_util.get_snapshot_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_base_url
    :summary:
    ```
* - {py:obj}`get_original_base_url <archivebox.core.routes_util.get_original_base_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.get_original_base_url
    :summary:
    ```
* - {py:obj}`build_admin_url <archivebox.core.routes_util.build_admin_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.build_admin_url
    :summary:
    ```
* - {py:obj}`build_web_url <archivebox.core.routes_util.build_web_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.build_web_url
    :summary:
    ```
* - {py:obj}`build_snapshot_url <archivebox.core.routes_util.build_snapshot_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.build_snapshot_url
    :summary:
    ```
* - {py:obj}`build_original_url <archivebox.core.routes_util.build_original_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util.build_original_url
    :summary:
    ```
* - {py:obj}`_build_url <archivebox.core.routes_util._build_url>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._build_url
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_SNAPSHOT_ID_RE <archivebox.core.routes_util._SNAPSHOT_ID_RE>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._SNAPSHOT_ID_RE
    :summary:
    ```
* - {py:obj}`_SNAPSHOT_SUBDOMAIN_RE <archivebox.core.routes_util._SNAPSHOT_SUBDOMAIN_RE>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._SNAPSHOT_SUBDOMAIN_RE
    :summary:
    ```
* - {py:obj}`_ROLE_SUBDOMAIN_LABELS <archivebox.core.routes_util._ROLE_SUBDOMAIN_LABELS>`
  - ```{autodoc2-docstring} archivebox.core.routes_util._ROLE_SUBDOMAIN_LABELS
    :summary:
    ```
````

### API

````{py:data} _SNAPSHOT_ID_RE
:canonical: archivebox.core.routes_util._SNAPSHOT_ID_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.core.routes_util._SNAPSHOT_ID_RE
```

````

````{py:data} _SNAPSHOT_SUBDOMAIN_RE
:canonical: archivebox.core.routes_util._SNAPSHOT_SUBDOMAIN_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.core.routes_util._SNAPSHOT_SUBDOMAIN_RE
```

````

````{py:data} _ROLE_SUBDOMAIN_LABELS
:canonical: archivebox.core.routes_util._ROLE_SUBDOMAIN_LABELS
:value: >
   ('admin', 'web', 'api')

```{autodoc2-docstring} archivebox.core.routes_util._ROLE_SUBDOMAIN_LABELS
```

````

````{py:function} split_host_port(host: str) -> tuple[str, str | None]
:canonical: archivebox.core.routes_util.split_host_port

```{autodoc2-docstring} archivebox.core.routes_util.split_host_port
```
````

````{py:function} _normalize_base_url(value: str | None) -> str
:canonical: archivebox.core.routes_util._normalize_base_url

```{autodoc2-docstring} archivebox.core.routes_util._normalize_base_url
```
````

````{py:function} normalize_base_url(value: str | None) -> str
:canonical: archivebox.core.routes_util.normalize_base_url

```{autodoc2-docstring} archivebox.core.routes_util.normalize_base_url
```
````

````{py:function} _csrf_trusted_origins(config) -> list[str]
:canonical: archivebox.core.routes_util._csrf_trusted_origins

```{autodoc2-docstring} archivebox.core.routes_util._csrf_trusted_origins
```
````

````{py:function} _allowed_hosts(config) -> set[str]
:canonical: archivebox.core.routes_util._allowed_hosts

```{autodoc2-docstring} archivebox.core.routes_util._allowed_hosts
```
````

````{py:function} derive_base_url_from_csrf(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.derive_base_url_from_csrf

```{autodoc2-docstring} archivebox.core.routes_util.derive_base_url_from_csrf
```
````

````{py:function} get_listen_host(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_listen_host

```{autodoc2-docstring} archivebox.core.routes_util.get_listen_host
```
````

````{py:function} get_listen_parts(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> tuple[str, str | None]
:canonical: archivebox.core.routes_util.get_listen_parts

```{autodoc2-docstring} archivebox.core.routes_util.get_listen_parts
```
````

````{py:function} _with_port(host: str, port: str | None) -> str
:canonical: archivebox.core.routes_util._with_port

```{autodoc2-docstring} archivebox.core.routes_util._with_port
```
````

````{py:function} strip_role_subdomain(host: str) -> str
:canonical: archivebox.core.routes_util.strip_role_subdomain

```{autodoc2-docstring} archivebox.core.routes_util.strip_role_subdomain
```
````

````{py:function} _is_local_bind_host(host: str) -> bool
:canonical: archivebox.core.routes_util._is_local_bind_host

```{autodoc2-docstring} archivebox.core.routes_util._is_local_bind_host
```
````

````{py:function} canonical_base_host_for_request(request_host: str) -> str
:canonical: archivebox.core.routes_util.canonical_base_host_for_request

```{autodoc2-docstring} archivebox.core.routes_util.canonical_base_host_for_request
```
````

````{py:function} _root_host_from_listen(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util._root_host_from_listen

```{autodoc2-docstring} archivebox.core.routes_util._root_host_from_listen
```
````

````{py:function} get_base_url(request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_base_url
```
````

````{py:function} get_base_host(request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_base_host

```{autodoc2-docstring} archivebox.core.routes_util.get_base_host
```
````

````{py:function} _build_base_host(subdomain: str | None, request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util._build_base_host

```{autodoc2-docstring} archivebox.core.routes_util._build_base_host
```
````

````{py:function} get_admin_host(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_admin_host

```{autodoc2-docstring} archivebox.core.routes_util.get_admin_host
```
````

````{py:function} get_web_host(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_web_host

```{autodoc2-docstring} archivebox.core.routes_util.get_web_host
```
````

````{py:function} get_api_host(config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_api_host

```{autodoc2-docstring} archivebox.core.routes_util.get_api_host
```
````

````{py:function} get_snapshot_subdomain(snapshot_id: str) -> str
:canonical: archivebox.core.routes_util.get_snapshot_subdomain

```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_subdomain
```
````

````{py:function} get_snapshot_host(snapshot_id: str, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_snapshot_host

```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_host
```
````

````{py:function} get_original_host(domain: str, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_original_host

```{autodoc2-docstring} archivebox.core.routes_util.get_original_host
```
````

````{py:function} is_snapshot_subdomain(subdomain: str) -> bool
:canonical: archivebox.core.routes_util.is_snapshot_subdomain

```{autodoc2-docstring} archivebox.core.routes_util.is_snapshot_subdomain
```
````

````{py:function} get_snapshot_lookup_key(snapshot_ref: str) -> str
:canonical: archivebox.core.routes_util.get_snapshot_lookup_key

```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_lookup_key
```
````

````{py:function} get_listen_subdomain(request_host: str, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_listen_subdomain

```{autodoc2-docstring} archivebox.core.routes_util.get_listen_subdomain
```
````

````{py:function} host_matches(request_host: str, target_host: str) -> bool
:canonical: archivebox.core.routes_util.host_matches

```{autodoc2-docstring} archivebox.core.routes_util.host_matches
```
````

````{py:function} is_allowed_archivebox_redirect_url(url: str | None, request=None, config: dict[str, typing.Any] | None = None) -> bool
:canonical: archivebox.core.routes_util.is_allowed_archivebox_redirect_url

```{autodoc2-docstring} archivebox.core.routes_util.is_allowed_archivebox_redirect_url
```
````

````{py:function} _scheme_from_request(request=None, config: dict[str, typing.Any] | None = None) -> str
:canonical: archivebox.core.routes_util._scheme_from_request

```{autodoc2-docstring} archivebox.core.routes_util._scheme_from_request
```
````

````{py:function} _build_base_url_for_host(host: str, request=None, config: dict[str, typing.Any] | None = None) -> str
:canonical: archivebox.core.routes_util._build_base_url_for_host

```{autodoc2-docstring} archivebox.core.routes_util._build_base_url_for_host
```
````

````{py:function} get_admin_base_url(request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_admin_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_admin_base_url
```
````

````{py:function} get_web_base_url(request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_web_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_web_base_url
```
````

````{py:function} get_api_base_url(request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_api_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_api_base_url
```
````

````{py:function} get_snapshot_base_url(snapshot_id: str, request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_snapshot_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_snapshot_base_url
```
````

````{py:function} get_original_base_url(domain: str, request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.get_original_base_url

```{autodoc2-docstring} archivebox.core.routes_util.get_original_base_url
```
````

````{py:function} build_admin_url(path: str = '', request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.build_admin_url

```{autodoc2-docstring} archivebox.core.routes_util.build_admin_url
```
````

````{py:function} build_web_url(path: str = '', request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.build_web_url

```{autodoc2-docstring} archivebox.core.routes_util.build_web_url
```
````

````{py:function} build_snapshot_url(snapshot_id: str, path: str = '', request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.build_snapshot_url

```{autodoc2-docstring} archivebox.core.routes_util.build_snapshot_url
```
````

````{py:function} build_original_url(domain: str, path: str = '', request=None, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> str
:canonical: archivebox.core.routes_util.build_original_url

```{autodoc2-docstring} archivebox.core.routes_util.build_original_url
```
````

````{py:function} _build_url(base_url: str, path: str) -> str
:canonical: archivebox.core.routes_util._build_url

```{autodoc2-docstring} archivebox.core.routes_util._build_url
```
````
