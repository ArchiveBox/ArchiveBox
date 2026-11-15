# {py:mod}`archivebox.config.configset`

```{py:module} archivebox.config.configset
```

```{autodoc2-docstring} archivebox.config.configset
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CaseConfigParser <archivebox.config.configset.CaseConfigParser>`
  -
* - {py:obj}`IniConfigSettingsSource <archivebox.config.configset.IniConfigSettingsSource>`
  - ```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource
    :summary:
    ```
* - {py:obj}`BaseConfigSet <archivebox.config.configset.BaseConfigSet>`
  - ```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`read_ini_config <archivebox.config.configset.read_ini_config>`
  - ```{autodoc2-docstring} archivebox.config.configset.read_ini_config
    :summary:
    ```
* - {py:obj}`_config_decoder <archivebox.config.configset._config_decoder>`
  - ```{autodoc2-docstring} archivebox.config.configset._config_decoder
    :summary:
    ```
* - {py:obj}`decode_config_inputs <archivebox.config.configset.decode_config_inputs>`
  - ```{autodoc2-docstring} archivebox.config.configset.decode_config_inputs
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`COMPUTED_CONFIG_KEYS <archivebox.config.configset.COMPUTED_CONFIG_KEYS>`
  - ```{autodoc2-docstring} archivebox.config.configset.COMPUTED_CONFIG_KEYS
    :summary:
    ```
* - {py:obj}`_PARSED_INI_CONFIG <archivebox.config.configset._PARSED_INI_CONFIG>`
  - ```{autodoc2-docstring} archivebox.config.configset._PARSED_INI_CONFIG
    :summary:
    ```
````

### API

````{py:data} COMPUTED_CONFIG_KEYS
:canonical: archivebox.config.configset.COMPUTED_CONFIG_KEYS
:value: >
   ('TERM_WIDTH', 'COMMIT_HASH', 'BUILD_TIME', 'USES_SUBDOMAIN_ROUTING', 'ENABLES_FULL_JS_REPLAY', 'CON...

```{autodoc2-docstring} archivebox.config.configset.COMPUTED_CONFIG_KEYS
```

````

`````{py:class} CaseConfigParser(defaults=None, dict_type=_default_dict, allow_no_value=False, *, delimiters=('=', ':'), comment_prefixes=('#', ';'), inline_comment_prefixes=None, strict=True, empty_lines_in_values=True, default_section=DEFAULTSECT, interpolation=_UNSET, converters=_UNSET)
:canonical: archivebox.config.configset.CaseConfigParser

Bases: {py:obj}`configparser.ConfigParser`

````{py:method} optionxform(optionstr: str) -> str
:canonical: archivebox.config.configset.CaseConfigParser.optionxform

```{autodoc2-docstring} archivebox.config.configset.CaseConfigParser.optionxform
```

````

`````

````{py:data} _PARSED_INI_CONFIG
:canonical: archivebox.config.configset._PARSED_INI_CONFIG
:type: tuple[pathlib.Path, str, dict[str, typing.Any]] | None
:value: >
   None

```{autodoc2-docstring} archivebox.config.configset._PARSED_INI_CONFIG
```

````

````{py:function} read_ini_config(config_path: str | pathlib.Path) -> dict[str, typing.Any]
:canonical: archivebox.config.configset.read_ini_config

```{autodoc2-docstring} archivebox.config.configset.read_ini_config
```
````

`````{py:class} IniConfigSettingsSource
:canonical: archivebox.config.configset.IniConfigSettingsSource

Bases: {py:obj}`pydantic_settings.PydanticBaseSettingsSource`

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource
```

````{py:method} get_field_value(field: typing.Any, field_name: str) -> tuple[typing.Any, str, bool]
:canonical: archivebox.config.configset.IniConfigSettingsSource.get_field_value

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource.get_field_value
```

````

````{py:method} __call__() -> dict[str, typing.Any]
:canonical: archivebox.config.configset.IniConfigSettingsSource.__call__

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource.__call__
```

````

````{py:method} _load_config_file() -> dict[str, typing.Any]
:canonical: archivebox.config.configset.IniConfigSettingsSource._load_config_file

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource._load_config_file
```

````

`````

````{py:function} _config_decoder(settings_cls: builtins.type[pydantic.BaseModel]) -> tuple[archivebox.config.configset.IniConfigSettingsSource, frozenset[str]]
:canonical: archivebox.config.configset._config_decoder

```{autodoc2-docstring} archivebox.config.configset._config_decoder
```
````

````{py:function} decode_config_inputs(settings_cls: builtins.type[pydantic.BaseModel], config: collections.abc.Mapping[str, typing.Any], *, decode_unknown_json: bool = False) -> dict[str, typing.Any]
:canonical: archivebox.config.configset.decode_config_inputs

```{autodoc2-docstring} archivebox.config.configset.decode_config_inputs
```
````

`````{py:class} BaseConfigSet
:canonical: archivebox.config.configset.BaseConfigSet

Bases: {py:obj}`pydantic.BaseModel`

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet
```

````{py:attribute} model_config
:canonical: archivebox.config.configset.BaseConfigSet.model_config
:value: >
   'SettingsConfigDict(...)'

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.model_config
```

````

````{py:attribute} computed_config_keys
:canonical: archivebox.config.configset.BaseConfigSet.computed_config_keys
:type: typing.ClassVar[tuple[str, ...]]
:value: >
   ()

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.computed_config_keys
```

````

````{py:method} settings_customise_sources(settings_cls: builtins.type[pydantic_settings.BaseSettings], init_settings: pydantic_settings.PydanticBaseSettingsSource, env_settings: pydantic_settings.PydanticBaseSettingsSource, dotenv_settings: pydantic_settings.PydanticBaseSettingsSource, file_secret_settings: pydantic_settings.PydanticBaseSettingsSource) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]
:canonical: archivebox.config.configset.BaseConfigSet.settings_customise_sources
:classmethod:

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.settings_customise_sources
```

````

````{py:method} load_from_file(config_path: pathlib.Path) -> dict[str, str]
:canonical: archivebox.config.configset.BaseConfigSet.load_from_file
:classmethod:

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.load_from_file
```

````

````{py:method} __getitem__(key: str) -> typing.Any
:canonical: archivebox.config.configset.BaseConfigSet.__getitem__

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.__getitem__
```

````

````{py:method} __setitem__(key: str, value: typing.Any) -> None
:canonical: archivebox.config.configset.BaseConfigSet.__setitem__

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.__setitem__
```

````

````{py:method} update(*args, **kwargs) -> None
:canonical: archivebox.config.configset.BaseConfigSet.update

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.update
```

````

````{py:method} __contains__(key: str) -> bool
:canonical: archivebox.config.configset.BaseConfigSet.__contains__

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.__contains__
```

````

````{py:method} get(key: str, default: typing.Any = None) -> typing.Any
:canonical: archivebox.config.configset.BaseConfigSet.get

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.get
```

````

````{py:method} as_dict() -> dict[str, typing.Any]
:canonical: archivebox.config.configset.BaseConfigSet.as_dict

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.as_dict
```

````

````{py:method} items()
:canonical: archivebox.config.configset.BaseConfigSet.items

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.items
```

````

````{py:method} keys()
:canonical: archivebox.config.configset.BaseConfigSet.keys

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.keys
```

````

````{py:method} values()
:canonical: archivebox.config.configset.BaseConfigSet.values

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.values
```

````

`````
