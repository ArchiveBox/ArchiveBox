# {py:mod}`archivebox.plugins.views`

```{py:module} archivebox.plugins.views
```

```{autodoc2-docstring} archivebox.plugins.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`render_code_block <archivebox.plugins.views.render_code_block>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_code_block
    :summary:
    ```
* - {py:obj}`render_highlighted_json_block <archivebox.plugins.views.render_highlighted_json_block>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_highlighted_json_block
    :summary:
    ```
* - {py:obj}`get_plugin_docs_url <archivebox.plugins.views.get_plugin_docs_url>`
  - ```{autodoc2-docstring} archivebox.plugins.views.get_plugin_docs_url
    :summary:
    ```
* - {py:obj}`get_plugin_hook_source_url <archivebox.plugins.views.get_plugin_hook_source_url>`
  - ```{autodoc2-docstring} archivebox.plugins.views.get_plugin_hook_source_url
    :summary:
    ```
* - {py:obj}`get_machine_admin_url <archivebox.plugins.views.get_machine_admin_url>`
  - ```{autodoc2-docstring} archivebox.plugins.views.get_machine_admin_url
    :summary:
    ```
* - {py:obj}`render_code_tag_list <archivebox.plugins.views.render_code_tag_list>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_code_tag_list
    :summary:
    ```
* - {py:obj}`render_link_tag_list <archivebox.plugins.views.render_link_tag_list>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_link_tag_list
    :summary:
    ```
* - {py:obj}`render_plugin_metadata_html <archivebox.plugins.views.render_plugin_metadata_html>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_plugin_metadata_html
    :summary:
    ```
* - {py:obj}`render_property_links <archivebox.plugins.views.render_property_links>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_property_links
    :summary:
    ```
* - {py:obj}`render_config_properties_html <archivebox.plugins.views.render_config_properties_html>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_config_properties_html
    :summary:
    ```
* - {py:obj}`render_hook_links_html <archivebox.plugins.views.render_hook_links_html>`
  - ```{autodoc2-docstring} archivebox.plugins.views.render_hook_links_html
    :summary:
    ```
* - {py:obj}`get_filesystem_plugins <archivebox.plugins.views.get_filesystem_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.views.get_filesystem_plugins
    :summary:
    ```
* - {py:obj}`find_plugin_for_config_key <archivebox.plugins.views.find_plugin_for_config_key>`
  - ```{autodoc2-docstring} archivebox.plugins.views.find_plugin_for_config_key
    :summary:
    ```
* - {py:obj}`get_config_definition_link <archivebox.plugins.views.get_config_definition_link>`
  - ```{autodoc2-docstring} archivebox.plugins.views.get_config_definition_link
    :summary:
    ```
* - {py:obj}`plugins_list_view <archivebox.plugins.views.plugins_list_view>`
  - ```{autodoc2-docstring} archivebox.plugins.views.plugins_list_view
    :summary:
    ```
* - {py:obj}`plugin_detail_view <archivebox.plugins.views.plugin_detail_view>`
  - ```{autodoc2-docstring} archivebox.plugins.views.plugin_detail_view
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ABX_PLUGINS_DOCS_BASE_URL <archivebox.plugins.views.ABX_PLUGINS_DOCS_BASE_URL>`
  - ```{autodoc2-docstring} archivebox.plugins.views.ABX_PLUGINS_DOCS_BASE_URL
    :summary:
    ```
* - {py:obj}`ABX_PLUGINS_GITHUB_BASE_URL <archivebox.plugins.views.ABX_PLUGINS_GITHUB_BASE_URL>`
  - ```{autodoc2-docstring} archivebox.plugins.views.ABX_PLUGINS_GITHUB_BASE_URL
    :summary:
    ```
* - {py:obj}`LIVE_PLUGIN_BASE_URL <archivebox.plugins.views.LIVE_PLUGIN_BASE_URL>`
  - ```{autodoc2-docstring} archivebox.plugins.views.LIVE_PLUGIN_BASE_URL
    :summary:
    ```
* - {py:obj}`JSON_TOKEN_RE <archivebox.plugins.views.JSON_TOKEN_RE>`
  - ```{autodoc2-docstring} archivebox.plugins.views.JSON_TOKEN_RE
    :summary:
    ```
````

### API

````{py:data} ABX_PLUGINS_DOCS_BASE_URL
:canonical: archivebox.plugins.views.ABX_PLUGINS_DOCS_BASE_URL
:value: >
   'https://archivebox.github.io/abx-plugins/'

```{autodoc2-docstring} archivebox.plugins.views.ABX_PLUGINS_DOCS_BASE_URL
```

````

````{py:data} ABX_PLUGINS_GITHUB_BASE_URL
:canonical: archivebox.plugins.views.ABX_PLUGINS_GITHUB_BASE_URL
:value: >
   'https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/'

```{autodoc2-docstring} archivebox.plugins.views.ABX_PLUGINS_GITHUB_BASE_URL
```

````

````{py:data} LIVE_PLUGIN_BASE_URL
:canonical: archivebox.plugins.views.LIVE_PLUGIN_BASE_URL
:value: >
   '/admin/environment/plugins/'

```{autodoc2-docstring} archivebox.plugins.views.LIVE_PLUGIN_BASE_URL
```

````

````{py:data} JSON_TOKEN_RE
:canonical: archivebox.plugins.views.JSON_TOKEN_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.plugins.views.JSON_TOKEN_RE
```

````

````{py:function} render_code_block(text: str, *, highlighted: bool = False) -> str
:canonical: archivebox.plugins.views.render_code_block

```{autodoc2-docstring} archivebox.plugins.views.render_code_block
```
````

````{py:function} render_highlighted_json_block(value: typing.Any) -> str
:canonical: archivebox.plugins.views.render_highlighted_json_block

```{autodoc2-docstring} archivebox.plugins.views.render_highlighted_json_block
```
````

````{py:function} get_plugin_docs_url(plugin_name: str) -> str
:canonical: archivebox.plugins.views.get_plugin_docs_url

```{autodoc2-docstring} archivebox.plugins.views.get_plugin_docs_url
```
````

````{py:function} get_plugin_hook_source_url(plugin_name: str, hook_name: str) -> str
:canonical: archivebox.plugins.views.get_plugin_hook_source_url

```{autodoc2-docstring} archivebox.plugins.views.get_plugin_hook_source_url
```
````

````{py:function} get_machine_admin_url() -> str | None
:canonical: archivebox.plugins.views.get_machine_admin_url

```{autodoc2-docstring} archivebox.plugins.views.get_machine_admin_url
```
````

````{py:function} render_code_tag_list(values: list[str]) -> str
:canonical: archivebox.plugins.views.render_code_tag_list

```{autodoc2-docstring} archivebox.plugins.views.render_code_tag_list
```
````

````{py:function} render_link_tag_list(values: list[str], url_resolver: collections.abc.Callable[[str], str] | None = None) -> str
:canonical: archivebox.plugins.views.render_link_tag_list

```{autodoc2-docstring} archivebox.plugins.views.render_link_tag_list
```
````

````{py:function} render_plugin_metadata_html(config: dict[str, typing.Any]) -> str
:canonical: archivebox.plugins.views.render_plugin_metadata_html

```{autodoc2-docstring} archivebox.plugins.views.render_plugin_metadata_html
```
````

````{py:function} render_property_links(prop_name: str, prop_info: dict[str, typing.Any], machine_admin_url: str | None) -> str
:canonical: archivebox.plugins.views.render_property_links

```{autodoc2-docstring} archivebox.plugins.views.render_property_links
```
````

````{py:function} render_config_properties_html(properties: dict[str, typing.Any], machine_admin_url: str | None) -> str
:canonical: archivebox.plugins.views.render_config_properties_html

```{autodoc2-docstring} archivebox.plugins.views.render_config_properties_html
```
````

````{py:function} render_hook_links_html(plugin_name: str, hooks: list[str], source: str) -> str
:canonical: archivebox.plugins.views.render_hook_links_html

```{autodoc2-docstring} archivebox.plugins.views.render_hook_links_html
```
````

````{py:function} get_filesystem_plugins() -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.plugins.views.get_filesystem_plugins

```{autodoc2-docstring} archivebox.plugins.views.get_filesystem_plugins
```
````

````{py:function} find_plugin_for_config_key(key: str) -> str | None
:canonical: archivebox.plugins.views.find_plugin_for_config_key

```{autodoc2-docstring} archivebox.plugins.views.find_plugin_for_config_key
```
````

````{py:function} get_config_definition_link(key: str) -> tuple[str, str]
:canonical: archivebox.plugins.views.get_config_definition_link

```{autodoc2-docstring} archivebox.plugins.views.get_config_definition_link
```
````

````{py:function} plugins_list_view(request: django.http.HttpRequest, **kwargs) -> admin_data_views.typing.TableContext
:canonical: archivebox.plugins.views.plugins_list_view

```{autodoc2-docstring} archivebox.plugins.views.plugins_list_view
```
````

````{py:function} plugin_detail_view(request: django.http.HttpRequest, key: str, **kwargs) -> admin_data_views.typing.ItemContext
:canonical: archivebox.plugins.views.plugin_detail_view

```{autodoc2-docstring} archivebox.plugins.views.plugin_detail_view
```
````
