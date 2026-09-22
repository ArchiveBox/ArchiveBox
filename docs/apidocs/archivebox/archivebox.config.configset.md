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

* - {py:obj}`_read_ini_config_cached <archivebox.config.configset._read_ini_config_cached>`
  - ```{autodoc2-docstring} archivebox.config.configset._read_ini_config_cached
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
* - {py:obj}`_INI_CACHE <archivebox.config.configset._INI_CACHE>`
  - ```{autodoc2-docstring} archivebox.config.configset._INI_CACHE
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

`````{py:class} CaseConfigParser(defaults=None, dict_type=_default_dict, allow_no_value=False, *, delimiters=('=', ':'), comment_prefixes=('#', ';'), inline_comment_prefixes=None, strict=True, empty_lines_in_values=True, default_section=DEFAULTSECT, interpolation=_UNSET, converters=_UNSET, allow_unnamed_section=False)
:canonical: archivebox.config.configset.CaseConfigParser

Bases: {py:obj}`configparser.ConfigParser`

````{py:method} optionxform(optionstr: str) -> str
:canonical: archivebox.config.configset.CaseConfigParser.optionxform

```{autodoc2-docstring} archivebox.config.configset.CaseConfigParser.optionxform
```

````

`````

````{py:data} _INI_CACHE
:canonical: archivebox.config.configset._INI_CACHE
:type: dict[tuple[str, float], dict[str, typing.Any]]
:value: >
   None

```{autodoc2-docstring} archivebox.config.configset._INI_CACHE
```

````

````{py:function} _read_ini_config_cached(config_path_str: str) -> dict[str, typing.Any]
:canonical: archivebox.config.configset._read_ini_config_cached

```{autodoc2-docstring} archivebox.config.configset._read_ini_config_cached
```
````

`````{py:class} IniConfigSettingsSource(settings_cls: type[pydantic_settings.main.BaseSettings])
:canonical: archivebox.config.configset.IniConfigSettingsSource

Bases: {py:obj}`pydantic_settings.PydanticBaseSettingsSource`

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.config.configset.IniConfigSettingsSource.__init__
```

````{py:method} get_field_value(field: typing.Any, field_name: str) -> tuple[typing.Any, str, bool]
:canonical: archivebox.config.configset.IniConfigSettingsSource.get_field_value

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

`````{py:class} BaseConfigSet(_case_sensitive: bool | None = None, _nested_model_default_partial_update: bool | None = None, _env_prefix: str | None = None, _env_prefix_target: pydantic_settings.sources.EnvPrefixTarget | None = None, _env_file: pydantic_settings.sources.DotenvType | None = ENV_FILE_SENTINEL, _env_file_encoding: str | None = None, _env_ignore_empty: bool | None = None, _env_nested_delimiter: str | None = None, _env_nested_max_split: int | None = None, _env_parse_none_str: str | None = None, _env_parse_enums: bool | None = None, _cli_prog_name: str | None = None, _cli_parse_args: bool | list[str] | tuple[str, ...] | None = None, _cli_settings_source: pydantic_settings.sources.CliSettingsSource[typing.Any] | None = None, _cli_parse_none_str: str | None = None, _cli_hide_none_type: bool | None = None, _cli_avoid_json: bool | None = None, _cli_enforce_required: bool | None = None, _cli_use_class_docs_for_groups: bool | None = None, _cli_exit_on_error: bool | None = None, _cli_prefix: str | None = None, _cli_flag_prefix_char: str | None = None, _cli_implicit_flags: bool | typing.Literal[dual, toggle] | None = None, _cli_ignore_unknown_args: bool | None = None, _cli_kebab_case: bool | typing.Literal[all, no_enums] | None = None, _cli_shortcuts: collections.abc.Mapping[str, str | list[str]] | None = None, _secrets_dir: pydantic_settings.sources.PathType | None = None, _build_sources: tuple[tuple[pydantic_settings.sources.PydanticBaseSettingsSource, ...], dict[str, typing.Any]] | None = None, **values: typing.Any)
:canonical: archivebox.config.configset.BaseConfigSet

Bases: {py:obj}`pydantic_settings.BaseSettings`

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.config.configset.BaseConfigSet.__init__
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

````{py:method} settings_customise_sources(settings_cls: type[pydantic_settings.BaseSettings], init_settings: pydantic_settings.PydanticBaseSettingsSource, env_settings: pydantic_settings.PydanticBaseSettingsSource, dotenv_settings: pydantic_settings.PydanticBaseSettingsSource, file_secret_settings: pydantic_settings.PydanticBaseSettingsSource) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]
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
