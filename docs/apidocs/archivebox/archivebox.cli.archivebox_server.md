# {py:mod}`archivebox.cli.archivebox_server`

```{py:module} archivebox.cli.archivebox_server
```

```{autodoc2-docstring} archivebox.cli.archivebox_server
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_is_ipv4_literal <archivebox.cli.archivebox_server._is_ipv4_literal>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._is_ipv4_literal
    :summary:
    ```
* - {py:obj}`_is_ipv6_literal <archivebox.cli.archivebox_server._is_ipv6_literal>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._is_ipv6_literal
    :summary:
    ```
* - {py:obj}`_bind_host_looks_like_ip <archivebox.cli.archivebox_server._bind_host_looks_like_ip>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._bind_host_looks_like_ip
    :summary:
    ```
* - {py:obj}`_split_bind_spec <archivebox.cli.archivebox_server._split_bind_spec>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._split_bind_spec
    :summary:
    ```
* - {py:obj}`_parse_and_validate_bind_spec <archivebox.cli.archivebox_server._parse_and_validate_bind_spec>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._parse_and_validate_bind_spec
    :summary:
    ```
* - {py:obj}`_print_server_startup_warnings <archivebox.cli.archivebox_server._print_server_startup_warnings>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._print_server_startup_warnings
    :summary:
    ```
* - {py:obj}`server <archivebox.cli.archivebox_server.server>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server.server
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_server.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server.main
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_IPV4_RE <archivebox.cli.archivebox_server._IPV4_RE>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._IPV4_RE
    :summary:
    ```
* - {py:obj}`_IPV6_CHARS_RE <archivebox.cli.archivebox_server._IPV6_CHARS_RE>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._IPV6_CHARS_RE
    :summary:
    ```
* - {py:obj}`_LOCAL_BIND_HOSTS <archivebox.cli.archivebox_server._LOCAL_BIND_HOSTS>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_server._LOCAL_BIND_HOSTS
    :summary:
    ```
````

### API

````{py:data} _IPV4_RE
:canonical: archivebox.cli.archivebox_server._IPV4_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.cli.archivebox_server._IPV4_RE
```

````

````{py:data} _IPV6_CHARS_RE
:canonical: archivebox.cli.archivebox_server._IPV6_CHARS_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.cli.archivebox_server._IPV6_CHARS_RE
```

````

````{py:data} _LOCAL_BIND_HOSTS
:canonical: archivebox.cli.archivebox_server._LOCAL_BIND_HOSTS
:value: >
   'frozenset(...)'

```{autodoc2-docstring} archivebox.cli.archivebox_server._LOCAL_BIND_HOSTS
```

````

````{py:function} _is_ipv4_literal(host: str) -> bool
:canonical: archivebox.cli.archivebox_server._is_ipv4_literal

```{autodoc2-docstring} archivebox.cli.archivebox_server._is_ipv4_literal
```
````

````{py:function} _is_ipv6_literal(host: str) -> bool
:canonical: archivebox.cli.archivebox_server._is_ipv6_literal

```{autodoc2-docstring} archivebox.cli.archivebox_server._is_ipv6_literal
```
````

````{py:function} _bind_host_looks_like_ip(host: str) -> bool
:canonical: archivebox.cli.archivebox_server._bind_host_looks_like_ip

```{autodoc2-docstring} archivebox.cli.archivebox_server._bind_host_looks_like_ip
```
````

````{py:function} _split_bind_spec(spec: str) -> tuple[str, str]
:canonical: archivebox.cli.archivebox_server._split_bind_spec

```{autodoc2-docstring} archivebox.cli.archivebox_server._split_bind_spec
```
````

````{py:function} _parse_and_validate_bind_spec(spec: str) -> tuple[str, str]
:canonical: archivebox.cli.archivebox_server._parse_and_validate_bind_spec

```{autodoc2-docstring} archivebox.cli.archivebox_server._parse_and_validate_bind_spec
```
````

````{py:function} _print_server_startup_warnings(config, host: str, port: str) -> None
:canonical: archivebox.cli.archivebox_server._print_server_startup_warnings

```{autodoc2-docstring} archivebox.cli.archivebox_server._print_server_startup_warnings
```
````

````{py:function} server(runserver_args: collections.abc.Iterable[str] | None = None, reload: bool = False, debug: bool = False, daemonize: bool = False, nothreading: bool = False, createsuperuser: bool = False) -> None
:canonical: archivebox.cli.archivebox_server.server

```{autodoc2-docstring} archivebox.cli.archivebox_server.server
```
````

````{py:function} main(**kwargs)
:canonical: archivebox.cli.archivebox_server.main

```{autodoc2-docstring} archivebox.cli.archivebox_server.main
```
````
