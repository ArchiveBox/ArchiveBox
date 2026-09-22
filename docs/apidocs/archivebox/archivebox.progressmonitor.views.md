# {py:mod}`archivebox.progressmonitor.views`

```{py:module} archivebox.progressmonitor.views
```

```{autodoc2-docstring} archivebox.progressmonitor.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`progress_endpoint <archivebox.progressmonitor.views.progress_endpoint>`
  - ```{autodoc2-docstring} archivebox.progressmonitor.views.progress_endpoint
    :summary:
    ```
* - {py:obj}`_live_progress_plugin_names <archivebox.progressmonitor.views._live_progress_plugin_names>`
  - ```{autodoc2-docstring} archivebox.progressmonitor.views._live_progress_plugin_names
    :summary:
    ```
* - {py:obj}`live_progress_view <archivebox.progressmonitor.views.live_progress_view>`
  - ```{autodoc2-docstring} archivebox.progressmonitor.views.live_progress_view
    :summary:
    ```
````

### API

````{py:function} progress_endpoint(scope: typing.Literal[crawl, snapshot] | None = None, object_id: object | None = None) -> str
:canonical: archivebox.progressmonitor.views.progress_endpoint

```{autodoc2-docstring} archivebox.progressmonitor.views.progress_endpoint
```
````

````{py:function} _live_progress_plugin_names() -> tuple[frozenset[str], frozenset[str]]
:canonical: archivebox.progressmonitor.views._live_progress_plugin_names

```{autodoc2-docstring} archivebox.progressmonitor.views._live_progress_plugin_names
```
````

````{py:function} live_progress_view(request)
:canonical: archivebox.progressmonitor.views.live_progress_view

```{autodoc2-docstring} archivebox.progressmonitor.views.live_progress_view
```
````
