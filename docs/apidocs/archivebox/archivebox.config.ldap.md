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

`````{py:class} LDAPConfig
:canonical: archivebox.config.ldap.LDAPConfig

Bases: {py:obj}`archivebox.config.configset.BaseConfigSet`

```{autodoc2-docstring} archivebox.config.ldap.LDAPConfig
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
