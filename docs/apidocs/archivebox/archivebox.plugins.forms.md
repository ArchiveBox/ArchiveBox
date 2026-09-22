# {py:mod}`archivebox.plugins.forms`

```{py:module} archivebox.plugins.forms
```

```{autodoc2-docstring} archivebox.plugins.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PluginConfigFormMixin <archivebox.plugins.forms.PluginConfigFormMixin>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_plugin_choices <archivebox.plugins.forms.get_plugin_choices>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_choices
    :summary:
    ```
* - {py:obj}`get_plugin_choice_label <archivebox.plugins.forms.get_plugin_choice_label>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_choice_label
    :summary:
    ```
* - {py:obj}`get_choice_field <archivebox.plugins.forms.get_choice_field>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.get_choice_field
    :summary:
    ```
* - {py:obj}`_plugin_config_input_name <archivebox.plugins.forms._plugin_config_input_name>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._plugin_config_input_name
    :summary:
    ```
* - {py:obj}`_schema_types <archivebox.plugins.forms._schema_types>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._schema_types
    :summary:
    ```
* - {py:obj}`_jsonish <archivebox.plugins.forms._jsonish>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._jsonish
    :summary:
    ```
* - {py:obj}`_same_config_value <archivebox.plugins.forms._same_config_value>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._same_config_value
    :summary:
    ```
* - {py:obj}`_coerce_plugin_config_value <archivebox.plugins.forms._coerce_plugin_config_value>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._coerce_plugin_config_value
    :summary:
    ```
* - {py:obj}`_resolve_required_binary_name <archivebox.plugins.forms._resolve_required_binary_name>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._resolve_required_binary_name
    :summary:
    ```
* - {py:obj}`_iter_required_binary_names <archivebox.plugins.forms._iter_required_binary_names>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._iter_required_binary_names
    :summary:
    ```
* - {py:obj}`_build_required_binary_url_lookup <archivebox.plugins.forms._build_required_binary_url_lookup>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._build_required_binary_url_lookup
    :summary:
    ```
* - {py:obj}`_build_required_binary_links <archivebox.plugins.forms._build_required_binary_links>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._build_required_binary_links
    :summary:
    ```
* - {py:obj}`get_plugin_config_binary_urls <archivebox.plugins.forms.get_plugin_config_binary_urls>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_config_binary_urls
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PLUGIN_CONFIG_FIELD_PREFIX <archivebox.plugins.forms.PLUGIN_CONFIG_FIELD_PREFIX>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.PLUGIN_CONFIG_FIELD_PREFIX
    :summary:
    ```
* - {py:obj}`PLUGIN_GROUP_DEFINITIONS <archivebox.plugins.forms.PLUGIN_GROUP_DEFINITIONS>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.PLUGIN_GROUP_DEFINITIONS
    :summary:
    ```
* - {py:obj}`HIDDEN_PLUGIN_CONFIG_UI_PLUGINS <archivebox.plugins.forms.HIDDEN_PLUGIN_CONFIG_UI_PLUGINS>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.HIDDEN_PLUGIN_CONFIG_UI_PLUGINS
    :summary:
    ```
* - {py:obj}`TIMEOUT_INPUT_PATTERN <archivebox.plugins.forms.TIMEOUT_INPUT_PATTERN>`
  - ```{autodoc2-docstring} archivebox.plugins.forms.TIMEOUT_INPUT_PATTERN
    :summary:
    ```
* - {py:obj}`_BINARY_TEMPLATE_PATTERN <archivebox.plugins.forms._BINARY_TEMPLATE_PATTERN>`
  - ```{autodoc2-docstring} archivebox.plugins.forms._BINARY_TEMPLATE_PATTERN
    :summary:
    ```
````

### API

````{py:data} PLUGIN_CONFIG_FIELD_PREFIX
:canonical: archivebox.plugins.forms.PLUGIN_CONFIG_FIELD_PREFIX
:value: >
   'plugin_config__'

```{autodoc2-docstring} archivebox.plugins.forms.PLUGIN_CONFIG_FIELD_PREFIX
```

````

````{py:data} PLUGIN_GROUP_DEFINITIONS
:canonical: archivebox.plugins.forms.PLUGIN_GROUP_DEFINITIONS
:value: >
   (('main_plugins', 'Main', '', '', '', ('dom', 'screenshot', 'pdf', 'singlefile', 'wget', 'archivedot...

```{autodoc2-docstring} archivebox.plugins.forms.PLUGIN_GROUP_DEFINITIONS
```

````

````{py:data} HIDDEN_PLUGIN_CONFIG_UI_PLUGINS
:canonical: archivebox.plugins.forms.HIDDEN_PLUGIN_CONFIG_UI_PLUGINS
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.forms.HIDDEN_PLUGIN_CONFIG_UI_PLUGINS
```

````

````{py:data} TIMEOUT_INPUT_PATTERN
:canonical: archivebox.plugins.forms.TIMEOUT_INPUT_PATTERN
:value: >
   '(0|[1-9][0-9]*|[0-9]+(?:\\.[0-9]+)?\\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs...'

```{autodoc2-docstring} archivebox.plugins.forms.TIMEOUT_INPUT_PATTERN
```

````

````{py:function} get_plugin_choices()
:canonical: archivebox.plugins.forms.get_plugin_choices

```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_choices
```
````

````{py:function} get_plugin_choice_label(plugin_name: str, plugin_configs: dict[str, dict]) -> str
:canonical: archivebox.plugins.forms.get_plugin_choice_label

```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_choice_label
```
````

````{py:function} get_choice_field(form: django.forms.Form, name: str) -> django.forms.ChoiceField
:canonical: archivebox.plugins.forms.get_choice_field

```{autodoc2-docstring} archivebox.plugins.forms.get_choice_field
```
````

````{py:function} _plugin_config_input_name(plugin_name: str, config_key: str) -> str
:canonical: archivebox.plugins.forms._plugin_config_input_name

```{autodoc2-docstring} archivebox.plugins.forms._plugin_config_input_name
```
````

````{py:function} _schema_types(schema: collections.abc.Mapping[str, typing.Any]) -> list[str]
:canonical: archivebox.plugins.forms._schema_types

```{autodoc2-docstring} archivebox.plugins.forms._schema_types
```
````

````{py:function} _jsonish(value: typing.Any) -> str
:canonical: archivebox.plugins.forms._jsonish

```{autodoc2-docstring} archivebox.plugins.forms._jsonish
```
````

````{py:function} _same_config_value(left: typing.Any, right: typing.Any) -> bool
:canonical: archivebox.plugins.forms._same_config_value

```{autodoc2-docstring} archivebox.plugins.forms._same_config_value
```
````

````{py:function} _coerce_plugin_config_value(raw_value: typing.Any, schema: collections.abc.Mapping[str, typing.Any]) -> typing.Any
:canonical: archivebox.plugins.forms._coerce_plugin_config_value

```{autodoc2-docstring} archivebox.plugins.forms._coerce_plugin_config_value
```
````

`````{py:class} PluginConfigFormMixin
:canonical: archivebox.plugins.forms.PluginConfigFormMixin

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin
```

````{py:attribute} plugin_groups
:canonical: archivebox.plugins.forms.PluginConfigFormMixin.plugin_groups
:type: list[dict[str, typing.Any]]
:value: >
   None

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin.plugin_groups
```

````

````{py:attribute} allow_crawl_execution_config_fields
:canonical: archivebox.plugins.forms.PluginConfigFormMixin.allow_crawl_execution_config_fields
:value: >
   True

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin.allow_crawl_execution_config_fields
```

````

````{py:method} build_plugin_groups(runtime_config: collections.abc.Mapping[str, typing.Any] | None = None) -> None
:canonical: archivebox.plugins.forms.PluginConfigFormMixin.build_plugin_groups

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin.build_plugin_groups
```

````

````{py:method} _build_plugin_cards(field_name: str, plugin_names: collections.abc.Iterable[str], plugin_configs: dict[str, dict[str, typing.Any]], runtime_config: collections.abc.Mapping[str, typing.Any], binary_url_lookup: collections.abc.Mapping[str, str] | None = None) -> list[dict[str, typing.Any]]
:canonical: archivebox.plugins.forms.PluginConfigFormMixin._build_plugin_cards

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin._build_plugin_cards
```

````

````{py:method} _build_plugin_config_field(plugin_name: str, config_key: str, prop_schema: collections.abc.Mapping[str, typing.Any], runtime_config: collections.abc.Mapping[str, typing.Any]) -> dict[str, typing.Any]
:canonical: archivebox.plugins.forms.PluginConfigFormMixin._build_plugin_config_field

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin._build_plugin_config_field
```

````

````{py:method} clean_plugin_config_overrides(effective_config: collections.abc.Mapping[str, typing.Any] | None = None) -> dict[str, typing.Any]
:canonical: archivebox.plugins.forms.PluginConfigFormMixin.clean_plugin_config_overrides

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin.clean_plugin_config_overrides
```

````

````{py:method} plugin_config_keys() -> set[str]
:canonical: archivebox.plugins.forms.PluginConfigFormMixin.plugin_config_keys

```{autodoc2-docstring} archivebox.plugins.forms.PluginConfigFormMixin.plugin_config_keys
```

````

`````

````{py:data} _BINARY_TEMPLATE_PATTERN
:canonical: archivebox.plugins.forms._BINARY_TEMPLATE_PATTERN
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.plugins.forms._BINARY_TEMPLATE_PATTERN
```

````

````{py:function} _resolve_required_binary_name(template_name: str, runtime_config: collections.abc.Mapping[str, typing.Any]) -> str
:canonical: archivebox.plugins.forms._resolve_required_binary_name

```{autodoc2-docstring} archivebox.plugins.forms._resolve_required_binary_name
```
````

````{py:function} _iter_required_binary_names(required_binaries: collections.abc.Iterable[typing.Any], runtime_config: collections.abc.Mapping[str, typing.Any]) -> collections.abc.Iterable[str]
:canonical: archivebox.plugins.forms._iter_required_binary_names

```{autodoc2-docstring} archivebox.plugins.forms._iter_required_binary_names
```
````

````{py:function} _build_required_binary_url_lookup(plugin_configs: collections.abc.Mapping[str, dict[str, typing.Any]], runtime_config: collections.abc.Mapping[str, typing.Any]) -> dict[str, str]
:canonical: archivebox.plugins.forms._build_required_binary_url_lookup

```{autodoc2-docstring} archivebox.plugins.forms._build_required_binary_url_lookup
```
````

````{py:function} _build_required_binary_links(required_binaries: list[dict[str, typing.Any]], runtime_config: collections.abc.Mapping[str, typing.Any], binary_url_lookup: collections.abc.Mapping[str, str] | None = None) -> list[dict[str, str]]
:canonical: archivebox.plugins.forms._build_required_binary_links

```{autodoc2-docstring} archivebox.plugins.forms._build_required_binary_links
```
````

````{py:function} get_plugin_config_binary_urls(runtime_config: collections.abc.Mapping[str, typing.Any]) -> dict[str, str]
:canonical: archivebox.plugins.forms.get_plugin_config_binary_urls

```{autodoc2-docstring} archivebox.plugins.forms.get_plugin_config_binary_urls
```
````
