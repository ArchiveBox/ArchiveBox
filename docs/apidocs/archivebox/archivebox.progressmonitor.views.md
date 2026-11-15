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
* - {py:obj}`_hook_details <archivebox.progressmonitor.views._hook_details>`
  - ```{autodoc2-docstring} archivebox.progressmonitor.views._hook_details
    :summary:
    ```
* - {py:obj}`_process_label <archivebox.progressmonitor.views._process_label>`
  - ```{autodoc2-docstring} archivebox.progressmonitor.views._process_label
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

````{py:function} _hook_details(hook_name: str, plugin: str = 'setup') -> tuple[str, str, str, str]
:canonical: archivebox.progressmonitor.views._hook_details

```{autodoc2-docstring} archivebox.progressmonitor.views._hook_details
```
````

````{py:function} _process_label(cmd: list | None) -> tuple[str, str, str, str]
:canonical: archivebox.progressmonitor.views._process_label

```{autodoc2-docstring} archivebox.progressmonitor.views._process_label
```
````

````{py:function} live_progress_view(request, *, authorized_snapshot=None)
:canonical: archivebox.progressmonitor.views.live_progress_view

```{autodoc2-docstring} archivebox.progressmonitor.views.live_progress_view
```
````
