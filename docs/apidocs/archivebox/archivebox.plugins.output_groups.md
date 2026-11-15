# {py:mod}`archivebox.plugins.output_groups`

```{py:module} archivebox.plugins.output_groups
```

```{autodoc2-docstring} archivebox.plugins.output_groups
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`output_group_for_plugin <archivebox.plugins.output_groups.output_group_for_plugin>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.output_group_for_plugin
    :summary:
    ```
* - {py:obj}`plugin_icon_is_hidden <archivebox.plugins.output_groups.plugin_icon_is_hidden>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_icon_is_hidden
    :summary:
    ```
* - {py:obj}`plugin_card_is_hidden <archivebox.plugins.output_groups.plugin_card_is_hidden>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_card_is_hidden
    :summary:
    ```
* - {py:obj}`display_plugin_name <archivebox.plugins.output_groups.display_plugin_name>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.display_plugin_name
    :summary:
    ```
* - {py:obj}`plugin_output_sizes <archivebox.plugins.output_groups.plugin_output_sizes>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_output_sizes
    :summary:
    ```
* - {py:obj}`order_output_plugins <archivebox.plugins.output_groups.order_output_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.order_output_plugins
    :summary:
    ```
* - {py:obj}`snapshot_thumbnail_result <archivebox.plugins.output_groups.snapshot_thumbnail_result>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.snapshot_thumbnail_result
    :summary:
    ```
* - {py:obj}`order_snapshot_outputs <archivebox.plugins.output_groups.order_snapshot_outputs>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.order_snapshot_outputs
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`OUTPUT_GROUPS <archivebox.plugins.output_groups.OUTPUT_GROUPS>`
  - ```{autodoc2-docstring} archivebox.plugins.output_groups.OUTPUT_GROUPS
    :summary:
    ```
````

### API

````{py:data} OUTPUT_GROUPS
:canonical: archivebox.plugins.output_groups.OUTPUT_GROUPS
:value: >
   (('html', 'Web'), ('article_text', 'Article text'), ('images', 'Images'), ('embedded_media', 'Embedd...

```{autodoc2-docstring} archivebox.plugins.output_groups.OUTPUT_GROUPS
```

````

````{py:function} output_group_for_plugin(plugin: str) -> str
:canonical: archivebox.plugins.output_groups.output_group_for_plugin

```{autodoc2-docstring} archivebox.plugins.output_groups.output_group_for_plugin
```
````

````{py:function} plugin_icon_is_hidden(plugin: str) -> bool
:canonical: archivebox.plugins.output_groups.plugin_icon_is_hidden

```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_icon_is_hidden
```
````

````{py:function} plugin_card_is_hidden(plugin: str) -> bool
:canonical: archivebox.plugins.output_groups.plugin_card_is_hidden

```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_card_is_hidden
```
````

````{py:function} display_plugin_name(plugin: str) -> str
:canonical: archivebox.plugins.output_groups.display_plugin_name

```{autodoc2-docstring} archivebox.plugins.output_groups.display_plugin_name
```
````

````{py:function} plugin_output_sizes(results) -> dict[str, int]
:canonical: archivebox.plugins.output_groups.plugin_output_sizes

```{autodoc2-docstring} archivebox.plugins.output_groups.plugin_output_sizes
```
````

````{py:function} order_output_plugins(plugins, sizes: dict[str, int]) -> list[str]
:canonical: archivebox.plugins.output_groups.order_output_plugins

```{autodoc2-docstring} archivebox.plugins.output_groups.order_output_plugins
```
````

````{py:function} snapshot_thumbnail_result(results)
:canonical: archivebox.plugins.output_groups.snapshot_thumbnail_result

```{autodoc2-docstring} archivebox.plugins.output_groups.snapshot_thumbnail_result
```
````

````{py:function} order_snapshot_outputs(outputs: list[dict[str, typing.Any]]) -> list[dict[str, typing.Any]]
:canonical: archivebox.plugins.output_groups.order_snapshot_outputs

```{autodoc2-docstring} archivebox.plugins.output_groups.order_snapshot_outputs
```
````
