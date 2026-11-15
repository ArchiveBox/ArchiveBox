# {py:mod}`archivebox.importers.views`

```{py:module} archivebox.importers.views
```

```{autodoc2-docstring} archivebox.importers.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`importer_admin <archivebox.importers.views.importer_admin>`
  - ```{autodoc2-docstring} archivebox.importers.views.importer_admin
    :summary:
    ```
* - {py:obj}`page <archivebox.importers.views.page>`
  - ```{autodoc2-docstring} archivebox.importers.views.page
    :summary:
    ```
* - {py:obj}`index <archivebox.importers.views.index>`
  - ```{autodoc2-docstring} archivebox.importers.views.index
    :summary:
    ```
* - {py:obj}`configure <archivebox.importers.views.configure>`
  - ```{autodoc2-docstring} archivebox.importers.views.configure
    :summary:
    ```
* - {py:obj}`detail <archivebox.importers.views.detail>`
  - ```{autodoc2-docstring} archivebox.importers.views.detail
    :summary:
    ```
* - {py:obj}`action <archivebox.importers.views.action>`
  - ```{autodoc2-docstring} archivebox.importers.views.action
    :summary:
    ```
* - {py:obj}`run_detail <archivebox.importers.views.run_detail>`
  - ```{autodoc2-docstring} archivebox.importers.views.run_detail
    :summary:
    ```
* - {py:obj}`source_activity <archivebox.importers.views.source_activity>`
  - ```{autodoc2-docstring} archivebox.importers.views.source_activity
    :summary:
    ```
* - {py:obj}`run_page <archivebox.importers.views.run_page>`
  - ```{autodoc2-docstring} archivebox.importers.views.run_page
    :summary:
    ```
* - {py:obj}`run_activity <archivebox.importers.views.run_activity>`
  - ```{autodoc2-docstring} archivebox.importers.views.run_activity
    :summary:
    ```
* - {py:obj}`run_artifact <archivebox.importers.views.run_artifact>`
  - ```{autodoc2-docstring} archivebox.importers.views.run_artifact
    :summary:
    ```
* - {py:obj}`run_json <archivebox.importers.views.run_json>`
  - ```{autodoc2-docstring} archivebox.importers.views.run_json
    :summary:
    ```
* - {py:obj}`guide_image <archivebox.importers.views.guide_image>`
  - ```{autodoc2-docstring} archivebox.importers.views.guide_image
    :summary:
    ```
* - {py:obj}`plugin_image <archivebox.importers.views.plugin_image>`
  - ```{autodoc2-docstring} archivebox.importers.views.plugin_image
    :summary:
    ```
* - {py:obj}`brand_icon <archivebox.importers.views.brand_icon>`
  - ```{autodoc2-docstring} archivebox.importers.views.brand_icon
    :summary:
    ```
* - {py:obj}`export_sources <archivebox.importers.views.export_sources>`
  - ```{autodoc2-docstring} archivebox.importers.views.export_sources
    :summary:
    ```
* - {py:obj}`export_runs <archivebox.importers.views.export_runs>`
  - ```{autodoc2-docstring} archivebox.importers.views.export_runs
    :summary:
    ```
````

### API

````{py:function} importer_admin(view)
:canonical: archivebox.importers.views.importer_admin

```{autodoc2-docstring} archivebox.importers.views.importer_admin
```
````

````{py:function} page(request, template, context)
:canonical: archivebox.importers.views.page

```{autodoc2-docstring} archivebox.importers.views.page
```
````

````{py:function} index(request)
:canonical: archivebox.importers.views.index

```{autodoc2-docstring} archivebox.importers.views.index
```
````

````{py:function} configure(request, plugin=None, feed=None, source_id=None)
:canonical: archivebox.importers.views.configure

```{autodoc2-docstring} archivebox.importers.views.configure
```
````

````{py:function} detail(request, source_id)
:canonical: archivebox.importers.views.detail

```{autodoc2-docstring} archivebox.importers.views.detail
```
````

````{py:function} action(request, source_id, action)
:canonical: archivebox.importers.views.action

```{autodoc2-docstring} archivebox.importers.views.action
```
````

````{py:function} run_detail(request, run_id)
:canonical: archivebox.importers.views.run_detail

```{autodoc2-docstring} archivebox.importers.views.run_detail
```
````

````{py:function} source_activity(request, source_id)
:canonical: archivebox.importers.views.source_activity

```{autodoc2-docstring} archivebox.importers.views.source_activity
```
````

````{py:function} run_page(source_id, number)
:canonical: archivebox.importers.views.run_page

```{autodoc2-docstring} archivebox.importers.views.run_page
```
````

````{py:function} run_activity(request, run_id)
:canonical: archivebox.importers.views.run_activity

```{autodoc2-docstring} archivebox.importers.views.run_activity
```
````

````{py:function} run_artifact(request, run_id, name, screenshot=False)
:canonical: archivebox.importers.views.run_artifact

```{autodoc2-docstring} archivebox.importers.views.run_artifact
```
````

````{py:function} run_json(request, run_id)
:canonical: archivebox.importers.views.run_json

```{autodoc2-docstring} archivebox.importers.views.run_json
```
````

````{py:function} guide_image(request, plugin, feed, step)
:canonical: archivebox.importers.views.guide_image

```{autodoc2-docstring} archivebox.importers.views.guide_image
```
````

````{py:function} plugin_image(request, plugin, filename)
:canonical: archivebox.importers.views.plugin_image

```{autodoc2-docstring} archivebox.importers.views.plugin_image
```
````

````{py:function} brand_icon(request, plugin, feed)
:canonical: archivebox.importers.views.brand_icon

```{autodoc2-docstring} archivebox.importers.views.brand_icon
```
````

````{py:function} export_sources(request, format)
:canonical: archivebox.importers.views.export_sources

```{autodoc2-docstring} archivebox.importers.views.export_sources
```
````

````{py:function} export_runs(request, source_id, format)
:canonical: archivebox.importers.views.export_runs

```{autodoc2-docstring} archivebox.importers.views.export_runs
```
````
