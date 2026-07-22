# {py:mod}`archivebox.plugins.hooks`

```{py:module} archivebox.plugins.hooks
```

```{autodoc2-docstring} archivebox.plugins.hooks
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ConfigDump <archivebox.plugins.hooks.ConfigDump>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_has_config_dump <archivebox.plugins.hooks._has_config_dump>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks._has_config_dump
    :summary:
    ```
* - {py:obj}`_config_to_overrides <archivebox.plugins.hooks._config_to_overrides>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks._config_to_overrides
    :summary:
    ```
* - {py:obj}`is_background_hook <archivebox.plugins.hooks.is_background_hook>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.is_background_hook
    :summary:
    ```
* - {py:obj}`normalize_hook_event_name <archivebox.plugins.hooks.normalize_hook_event_name>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.normalize_hook_event_name
    :summary:
    ```
* - {py:obj}`_model_output_dir_from_child_path <archivebox.plugins.hooks._model_output_dir_from_child_path>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks._model_output_dir_from_child_path
    :summary:
    ```
* - {py:obj}`discover_hooks <archivebox.plugins.hooks.discover_hooks>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.discover_hooks
    :summary:
    ```
* - {py:obj}`run_hook <archivebox.plugins.hooks.run_hook>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.run_hook
    :summary:
    ```
* - {py:obj}`extract_records_from_process <archivebox.plugins.hooks.extract_records_from_process>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.extract_records_from_process
    :summary:
    ```
* - {py:obj}`collect_urls_from_plugins <archivebox.plugins.hooks.collect_urls_from_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.collect_urls_from_plugins
    :summary:
    ```
* - {py:obj}`process_hook_records <archivebox.plugins.hooks.process_hook_records>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.process_hook_records
    :summary:
    ```
````

### API

`````{py:class} ConfigDump
:canonical: archivebox.plugins.hooks.ConfigDump

Bases: {py:obj}`typing.Protocol`

````{py:method} as_dict() -> dict[str, typing.Any]
:canonical: archivebox.plugins.hooks.ConfigDump.as_dict

```{autodoc2-docstring} archivebox.plugins.hooks.ConfigDump.as_dict
```

````

`````

````{py:function} _has_config_dump(config: object) -> typing.TypeGuard[archivebox.plugins.hooks.ConfigDump]
:canonical: archivebox.plugins.hooks._has_config_dump

```{autodoc2-docstring} archivebox.plugins.hooks._has_config_dump
```
````

````{py:function} _config_to_overrides(config: archivebox.plugins.discovery.ConfigLookup | collections.abc.Mapping[str, typing.Any] | None) -> dict[str, typing.Any]
:canonical: archivebox.plugins.hooks._config_to_overrides

```{autodoc2-docstring} archivebox.plugins.hooks._config_to_overrides
```
````

````{py:function} is_background_hook(hook_name: str) -> bool
:canonical: archivebox.plugins.hooks.is_background_hook

```{autodoc2-docstring} archivebox.plugins.hooks.is_background_hook
```
````

````{py:function} normalize_hook_event_name(event_name: str) -> str | None
:canonical: archivebox.plugins.hooks.normalize_hook_event_name

```{autodoc2-docstring} archivebox.plugins.hooks.normalize_hook_event_name
```
````

````{py:function} _model_output_dir_from_child_path(path: pathlib.Path, marker: str) -> pathlib.Path | None
:canonical: archivebox.plugins.hooks._model_output_dir_from_child_path

```{autodoc2-docstring} archivebox.plugins.hooks._model_output_dir_from_child_path
```
````

````{py:function} discover_hooks(event_name: str, filter_disabled: bool = True, config: archivebox.plugins.discovery.ConfigLookup | None = None, **config_kwargs: typing.Any) -> list[pathlib.Path]
:canonical: archivebox.plugins.hooks.discover_hooks

```{autodoc2-docstring} archivebox.plugins.hooks.discover_hooks
```
````

````{py:function} run_hook(script: pathlib.Path, output_dir: pathlib.Path, config: archivebox.plugins.discovery.ConfigLookup | collections.abc.Mapping[str, typing.Any] | None = None, timeout: int | None = None, parent: typing.Optional[archivebox.machine.models.Process] = None, **kwargs: typing.Any) -> archivebox.machine.models.Process
:canonical: archivebox.plugins.hooks.run_hook

```{autodoc2-docstring} archivebox.plugins.hooks.run_hook
```
````

````{py:function} extract_records_from_process(process: archivebox.machine.models.Process) -> list[dict[str, typing.Any]]
:canonical: archivebox.plugins.hooks.extract_records_from_process

```{autodoc2-docstring} archivebox.plugins.hooks.extract_records_from_process
```
````

````{py:function} collect_urls_from_plugins(snapshot_dir: pathlib.Path) -> list[dict[str, typing.Any]]
:canonical: archivebox.plugins.hooks.collect_urls_from_plugins

```{autodoc2-docstring} archivebox.plugins.hooks.collect_urls_from_plugins
```
````

````{py:function} process_hook_records(records: list[dict[str, typing.Any]], overrides: dict[str, typing.Any] | None = None) -> dict[str, int]
:canonical: archivebox.plugins.hooks.process_hook_records

```{autodoc2-docstring} archivebox.plugins.hooks.process_hook_records
```
````
