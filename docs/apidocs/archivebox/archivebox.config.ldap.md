# {py:mod}`archivebox.config.ldap`

```{py:module} archivebox.config.ldap
```

```{autodoc2-docstring} archivebox.config.ldap
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LDAPConfig <archivebox.config.ldap.LDAPConfig>`
  - ```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig
    :summary:
    ```
````

### API

`````{py:class} LDAPConfig(_case_sensitive: bool | None = None, _nested_model_default_partial_update: bool | None = None, _env_prefix: str | None = None, _env_prefix_target: pydantic_settings.sources.EnvPrefixTarget | None = None, _env_file: pydantic_settings.sources.DotenvType | None = ENV_FILE_SENTINEL, _env_file_encoding: str | None = None, _env_ignore_empty: bool | None = None, _env_nested_delimiter: str | None = None, _env_nested_max_split: int | None = None, _env_parse_none_str: str | None = None, _env_parse_enums: bool | None = None, _cli_prog_name: str | None = None, _cli_parse_args: bool | list[str] | tuple[str, ...] | None = None, _cli_settings_source: pydantic_settings.sources.CliSettingsSource[typing.Any] | None = None, _cli_parse_none_str: str | None = None, _cli_hide_none_type: bool | None = None, _cli_avoid_json: bool | None = None, _cli_enforce_required: bool | None = None, _cli_use_class_docs_for_groups: bool | None = None, _cli_exit_on_error: bool | None = None, _cli_prefix: str | None = None, _cli_flag_prefix_char: str | None = None, _cli_implicit_flags: bool | typing.Literal[dual, toggle] | None = None, _cli_ignore_unknown_args: bool | None = None, _cli_kebab_case: bool | typing.Literal[all, no_enums] | None = None, _cli_shortcuts: collections.abc.Mapping[str, str | list[str]] | None = None, _secrets_dir: pydantic_settings.sources.PathType | None = None, _build_sources: tuple[tuple[pydantic_settings.sources.PydanticBaseSettingsSource, ...], dict[str, typing.Any]] | None = None, **values: typing.Any)
:canonical: archivebox.config.ldap.LDAPConfig

Bases: {py:obj}`archivebox.config.configset.BaseConfigSet`

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.__init__
```

````{py:attribute} toml_section_header
:canonical: archivebox.config.ldap.LDAPConfig.toml_section_header
:type: str
:value: >
   'LDAP_CONFIG'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.toml_section_header
```

````

````{py:attribute} _scope
:canonical: archivebox.config.ldap.LDAPConfig._scope
:type: str
:value: >
   'PrivateAttr(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig._scope
```

````

````{py:attribute} LDAP_ENABLED
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_ENABLED
:type: bool
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_ENABLED
```

````

````{py:attribute} LDAP_SERVER_URI
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_SERVER_URI
:type: str | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_SERVER_URI
```

````

````{py:attribute} LDAP_BIND_DN
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_BIND_DN
:type: str | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_BIND_DN
```

````

````{py:attribute} LDAP_BIND_PASSWORD
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_BIND_PASSWORD
:type: str | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_BIND_PASSWORD
```

````

````{py:attribute} LDAP_USER_BASE
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_USER_BASE
:type: str | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_USER_BASE
```

````

````{py:attribute} LDAP_USER_FILTER
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_USER_FILTER
:type: str
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_USER_FILTER
```

````

````{py:attribute} LDAP_USERNAME_ATTR
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_USERNAME_ATTR
:type: str
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_USERNAME_ATTR
```

````

````{py:attribute} LDAP_FIRSTNAME_ATTR
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_FIRSTNAME_ATTR
:type: str
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_FIRSTNAME_ATTR
```

````

````{py:attribute} LDAP_LASTNAME_ATTR
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_LASTNAME_ATTR
:type: str
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_LASTNAME_ATTR
```

````

````{py:attribute} LDAP_EMAIL_ATTR
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_EMAIL_ATTR
:type: str
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_EMAIL_ATTR
```

````

````{py:attribute} LDAP_CREATE_SUPERUSER
:canonical: archivebox.config.ldap.LDAPConfig.LDAP_CREATE_SUPERUSER
:type: bool
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.LDAP_CREATE_SUPERUSER
```

````

````{py:method} validate_ldap_config() -> tuple[bool, str]
:canonical: archivebox.config.ldap.LDAPConfig.validate_ldap_config

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig.validate_ldap_config
```

````

`````
