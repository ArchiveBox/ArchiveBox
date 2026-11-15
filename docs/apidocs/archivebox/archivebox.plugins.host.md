# {py:mod}`archivebox.plugins.host`

```{py:module} archivebox.plugins.host
```

```{autodoc2-docstring} archivebox.plugins.host
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveBoxHost <archivebox.plugins.host.ArchiveBoxHost>`
  - ```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`host <archivebox.plugins.host.host>`
  - ```{autodoc2-docstring} archivebox.plugins.host.host
    :summary:
    ```
````

### API

`````{py:class} ArchiveBoxHost
:canonical: archivebox.plugins.host.ArchiveBoxHost

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost
```

````{py:method} request_config(request=None)
:canonical: archivebox.plugins.host.ArchiveBoxHost.request_config

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.request_config
```

````

````{py:method} admin_context(request)
:canonical: archivebox.plugins.host.ArchiveBoxHost.admin_context

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.admin_context
```

````

````{py:method} route_urls(request)
:canonical: archivebox.plugins.host.ArchiveBoxHost.route_urls

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.route_urls
```

````

````{py:method} authenticate(request, *, api=False)
:canonical: archivebox.plugins.host.ArchiveBoxHost.authenticate

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.authenticate
```

````

````{py:method} capture_context(request, *, snapshot_id=None, crawl_id=None)
:canonical: archivebox.plugins.host.ArchiveBoxHost.capture_context

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.capture_context
```

````

````{py:method} websocket_request(scope)
:canonical: archivebox.plugins.host.ArchiveBoxHost.websocket_request

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.websocket_request
```

````

````{py:method} browser_sources()
:canonical: archivebox.plugins.host.ArchiveBoxHost.browser_sources

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.browser_sources
```

````

````{py:method} browser_binding(*, persona_name=None, snapshot_id=None, crawl_id=None, browser_id=None, current=False, create=False)
:canonical: archivebox.plugins.host.ArchiveBoxHost.browser_binding

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.browser_binding
```

````

````{py:method} cli_command(plugin, command)
:canonical: archivebox.plugins.host.ArchiveBoxHost.cli_command

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.cli_command
```

````

````{py:method} collection_context(*, crawl_id=None, limit=20)
:canonical: archivebox.plugins.host.ArchiveBoxHost.collection_context

```{autodoc2-docstring} archivebox.plugins.host.ArchiveBoxHost.collection_context
```

````

`````

````{py:data} host
:canonical: archivebox.plugins.host.host
:value: >
   'ArchiveBoxHost(...)'

```{autodoc2-docstring} archivebox.plugins.host.host
```

````
