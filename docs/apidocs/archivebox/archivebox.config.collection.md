# {py:mod}`archivebox.config.collection`

```{py:module} archivebox.config.collection
```

```{autodoc2-docstring} archivebox.config.collection
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_coerce_to_str_dict <archivebox.config.collection._coerce_to_str_dict>`
  - ```{autodoc2-docstring} archivebox.config.collection._coerce_to_str_dict
    :summary:
    ```
* - {py:obj}`_load_file_config_dict <archivebox.config.collection._load_file_config_dict>`
  - ```{autodoc2-docstring} archivebox.config.collection._load_file_config_dict
    :summary:
    ```
* - {py:obj}`_resolve_section_for_key <archivebox.config.collection._resolve_section_for_key>`
  - ```{autodoc2-docstring} archivebox.config.collection._resolve_section_for_key
    :summary:
    ```
* - {py:obj}`_render_config_file_content <archivebox.config.collection._render_config_file_content>`
  - ```{autodoc2-docstring} archivebox.config.collection._render_config_file_content
    :summary:
    ```
* - {py:obj}`_write_file_if_changed <archivebox.config.collection._write_file_if_changed>`
  - ```{autodoc2-docstring} archivebox.config.collection._write_file_if_changed
    :summary:
    ```
* - {py:obj}`mirror_machine_config_to_file <archivebox.config.collection.mirror_machine_config_to_file>`
  - ```{autodoc2-docstring} archivebox.config.collection.mirror_machine_config_to_file
    :summary:
    ```
* - {py:obj}`_coerce_from_str_dict <archivebox.config.collection._coerce_from_str_dict>`
  - ```{autodoc2-docstring} archivebox.config.collection._coerce_from_str_dict
    :summary:
    ```
* - {py:obj}`_mirror_file_to_machine_config <archivebox.config.collection._mirror_file_to_machine_config>`
  - ```{autodoc2-docstring} archivebox.config.collection._mirror_file_to_machine_config
    :summary:
    ```
* - {py:obj}`sync_machine_and_file <archivebox.config.collection.sync_machine_and_file>`
  - ```{autodoc2-docstring} archivebox.config.collection.sync_machine_and_file
    :summary:
    ```
* - {py:obj}`write_config_file <archivebox.config.collection.write_config_file>`
  - ```{autodoc2-docstring} archivebox.config.collection.write_config_file
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CONFIG_FILE_HEADER <archivebox.config.collection.CONFIG_FILE_HEADER>`
  - ```{autodoc2-docstring} archivebox.config.collection.CONFIG_FILE_HEADER
    :summary:
    ```
* - {py:obj}`_MIRROR_IN_PROGRESS <archivebox.config.collection._MIRROR_IN_PROGRESS>`
  - ```{autodoc2-docstring} archivebox.config.collection._MIRROR_IN_PROGRESS
    :summary:
    ```
* - {py:obj}`_INITIAL_SYNC_DONE <archivebox.config.collection._INITIAL_SYNC_DONE>`
  - ```{autodoc2-docstring} archivebox.config.collection._INITIAL_SYNC_DONE
    :summary:
    ```
````

### API

````{py:data} CONFIG_FILE_HEADER
:canonical: archivebox.config.collection.CONFIG_FILE_HEADER
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.config.collection.CONFIG_FILE_HEADER
```

````

````{py:data} _MIRROR_IN_PROGRESS
:canonical: archivebox.config.collection._MIRROR_IN_PROGRESS
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.collection._MIRROR_IN_PROGRESS
```

````

````{py:data} _INITIAL_SYNC_DONE
:canonical: archivebox.config.collection._INITIAL_SYNC_DONE
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.collection._INITIAL_SYNC_DONE
```

````

````{py:function} _coerce_to_str_dict(config: typing.Any) -> dict[str, str]
:canonical: archivebox.config.collection._coerce_to_str_dict

```{autodoc2-docstring} archivebox.config.collection._coerce_to_str_dict
```
````

````{py:function} _load_file_config_dict() -> tuple[dict[str, str], float | None]
:canonical: archivebox.config.collection._load_file_config_dict

```{autodoc2-docstring} archivebox.config.collection._load_file_config_dict
```
````

````{py:function} _resolve_section_for_key(key: str, config_sections, plugin_configs) -> str
:canonical: archivebox.config.collection._resolve_section_for_key

```{autodoc2-docstring} archivebox.config.collection._resolve_section_for_key
```
````

````{py:function} _render_config_file_content(config: dict[str, str]) -> str
:canonical: archivebox.config.collection._render_config_file_content

```{autodoc2-docstring} archivebox.config.collection._render_config_file_content
```
````

````{py:function} _write_file_if_changed(content: str) -> bool
:canonical: archivebox.config.collection._write_file_if_changed

```{autodoc2-docstring} archivebox.config.collection._write_file_if_changed
```
````

````{py:function} mirror_machine_config_to_file(config: typing.Any) -> None
:canonical: archivebox.config.collection.mirror_machine_config_to_file

```{autodoc2-docstring} archivebox.config.collection.mirror_machine_config_to_file
```
````

````{py:function} _coerce_from_str_dict(file_config: dict[str, str]) -> dict[str, typing.Any]
:canonical: archivebox.config.collection._coerce_from_str_dict

```{autodoc2-docstring} archivebox.config.collection._coerce_from_str_dict
```
````

````{py:function} _mirror_file_to_machine_config(file_config: dict[str, str]) -> None
:canonical: archivebox.config.collection._mirror_file_to_machine_config

```{autodoc2-docstring} archivebox.config.collection._mirror_file_to_machine_config
```
````

````{py:function} sync_machine_and_file(machine: typing.Any = None) -> None
:canonical: archivebox.config.collection.sync_machine_and_file

```{autodoc2-docstring} archivebox.config.collection.sync_machine_and_file
```
````

````{py:function} write_config_file(config: dict[str, str]) -> archivebox.misc.logging.AttrDict
:canonical: archivebox.config.collection.write_config_file

```{autodoc2-docstring} archivebox.config.collection.write_config_file
```
````
