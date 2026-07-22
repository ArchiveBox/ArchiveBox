# {py:mod}`archivebox.plugins.discovery`

```{py:module} archivebox.plugins.discovery
```

```{autodoc2-docstring} archivebox.plugins.discovery
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ConfigLookup <archivebox.plugins.discovery.ConfigLookup>`
  -
* - {py:obj}`PluginSpecialConfig <archivebox.plugins.discovery.PluginSpecialConfig>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`iter_plugin_dirs <archivebox.plugins.discovery.iter_plugin_dirs>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.iter_plugin_dirs
    :summary:
    ```
* - {py:obj}`get_plugins <archivebox.plugins.discovery.get_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugins
    :summary:
    ```
* - {py:obj}`get_plugin_models <archivebox.plugins.discovery.get_plugin_models>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_models
    :summary:
    ```
* - {py:obj}`get_plugin_name <archivebox.plugins.discovery.get_plugin_name>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_name
    :summary:
    ```
* - {py:obj}`get_enabled_plugins <archivebox.plugins.discovery.get_enabled_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_enabled_plugins
    :summary:
    ```
* - {py:obj}`discover_plugins_that_provide_interface <archivebox.plugins.discovery.discover_plugins_that_provide_interface>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.discover_plugins_that_provide_interface
    :summary:
    ```
* - {py:obj}`get_search_backends <archivebox.plugins.discovery.get_search_backends>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_search_backends
    :summary:
    ```
* - {py:obj}`discover_plugin_configs <archivebox.plugins.discovery.discover_plugin_configs>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.discover_plugin_configs
    :summary:
    ```
* - {py:obj}`get_plugin_special_config <archivebox.plugins.discovery.get_plugin_special_config>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_special_config
    :summary:
    ```
* - {py:obj}`get_plugin_template <archivebox.plugins.discovery.get_plugin_template>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_template
    :summary:
    ```
* - {py:obj}`get_plugin_icon <archivebox.plugins.discovery.get_plugin_icon>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_icon
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BUILTIN_PLUGINS_DIR <archivebox.plugins.discovery.BUILTIN_PLUGINS_DIR>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.BUILTIN_PLUGINS_DIR
    :summary:
    ```
* - {py:obj}`USER_PLUGINS_DIR <archivebox.plugins.discovery.USER_PLUGINS_DIR>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.USER_PLUGINS_DIR
    :summary:
    ```
* - {py:obj}`DEFAULT_TEMPLATES <archivebox.plugins.discovery.DEFAULT_TEMPLATES>`
  - ```{autodoc2-docstring} archivebox.plugins.discovery.DEFAULT_TEMPLATES
    :summary:
    ```
````

### API

`````{py:class} ConfigLookup
:canonical: archivebox.plugins.discovery.ConfigLookup

Bases: {py:obj}`typing.Protocol`

````{py:method} get(key: str, default: typing.Any = None) -> typing.Any
:canonical: archivebox.plugins.discovery.ConfigLookup.get

```{autodoc2-docstring} archivebox.plugins.discovery.ConfigLookup.get
```

````

````{py:method} items() -> collections.abc.Iterable[tuple[str, typing.Any]]
:canonical: archivebox.plugins.discovery.ConfigLookup.items

```{autodoc2-docstring} archivebox.plugins.discovery.ConfigLookup.items
```

````

`````

`````{py:class} PluginSpecialConfig()
:canonical: archivebox.plugins.discovery.PluginSpecialConfig

Bases: {py:obj}`typing.TypedDict`

````{py:attribute} enabled
:canonical: archivebox.plugins.discovery.PluginSpecialConfig.enabled
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.discovery.PluginSpecialConfig.enabled
```

````

````{py:attribute} timeout
:canonical: archivebox.plugins.discovery.PluginSpecialConfig.timeout
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.discovery.PluginSpecialConfig.timeout
```

````

````{py:attribute} binary
:canonical: archivebox.plugins.discovery.PluginSpecialConfig.binary
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.discovery.PluginSpecialConfig.binary
```

````

`````

````{py:data} BUILTIN_PLUGINS_DIR
:canonical: archivebox.plugins.discovery.BUILTIN_PLUGINS_DIR
:value: >
   'resolve(...)'

```{autodoc2-docstring} archivebox.plugins.discovery.BUILTIN_PLUGINS_DIR
```

````

````{py:data} USER_PLUGINS_DIR
:canonical: archivebox.plugins.discovery.USER_PLUGINS_DIR
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.discovery.USER_PLUGINS_DIR
```

````

````{py:function} iter_plugin_dirs() -> list[pathlib.Path]
:canonical: archivebox.plugins.discovery.iter_plugin_dirs

```{autodoc2-docstring} archivebox.plugins.discovery.iter_plugin_dirs
```
````

````{py:function} get_plugins() -> list[str]
:canonical: archivebox.plugins.discovery.get_plugins

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugins
```
````

````{py:function} get_plugin_models()
:canonical: archivebox.plugins.discovery.get_plugin_models

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_models
```
````

````{py:function} get_plugin_name(plugin: str) -> str
:canonical: archivebox.plugins.discovery.get_plugin_name

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_name
```
````

````{py:function} get_enabled_plugins(config: archivebox.plugins.discovery.ConfigLookup | None = None, **config_kwargs: typing.Any) -> list[str]
:canonical: archivebox.plugins.discovery.get_enabled_plugins

```{autodoc2-docstring} archivebox.plugins.discovery.get_enabled_plugins
```
````

````{py:function} discover_plugins_that_provide_interface(module_name: str, required_attrs: list[str], plugin_prefix: str | None = None) -> dict[str, typing.Any]
:canonical: archivebox.plugins.discovery.discover_plugins_that_provide_interface

```{autodoc2-docstring} archivebox.plugins.discovery.discover_plugins_that_provide_interface
```
````

````{py:function} get_search_backends() -> dict[str, typing.Any]
:canonical: archivebox.plugins.discovery.get_search_backends

```{autodoc2-docstring} archivebox.plugins.discovery.get_search_backends
```
````

````{py:function} discover_plugin_configs() -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.plugins.discovery.discover_plugin_configs

```{autodoc2-docstring} archivebox.plugins.discovery.discover_plugin_configs
```
````

````{py:function} get_plugin_special_config(plugin_name: str, config: archivebox.plugins.discovery.ConfigLookup, _visited: set[str] | None = None) -> archivebox.plugins.discovery.PluginSpecialConfig
:canonical: archivebox.plugins.discovery.get_plugin_special_config

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_special_config
```
````

````{py:data} DEFAULT_TEMPLATES
:canonical: archivebox.plugins.discovery.DEFAULT_TEMPLATES
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.discovery.DEFAULT_TEMPLATES
```

````

````{py:function} get_plugin_template(plugin: str, template_name: str, fallback: bool = True) -> str | None
:canonical: archivebox.plugins.discovery.get_plugin_template

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_template
```
````

````{py:function} get_plugin_icon(plugin: str) -> str
:canonical: archivebox.plugins.discovery.get_plugin_icon

```{autodoc2-docstring} archivebox.plugins.discovery.get_plugin_icon
```
````
