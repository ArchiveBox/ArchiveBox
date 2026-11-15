# {py:mod}`archivebox.config.allauth`

```{py:module} archivebox.config.allauth
```

```{autodoc2-docstring} archivebox.config.allauth
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AllauthConfig <archivebox.config.allauth.AllauthConfig>`
  -
````

### API

`````{py:class} AllauthConfig
:canonical: archivebox.config.allauth.AllauthConfig

Bases: {py:obj}`archivebox.config.configset.BaseConfigSet`

````{py:attribute} toml_section_header
:canonical: archivebox.config.allauth.AllauthConfig.toml_section_header
:type: str
:value: >
   'ALLAUTH_CONFIG'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.toml_section_header
```

````

````{py:attribute} _scope
:canonical: archivebox.config.allauth.AllauthConfig._scope
:type: str
:value: >
   'PrivateAttr(...)'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig._scope
```

````

````{py:attribute} ALLAUTH_ENABLED
:canonical: archivebox.config.allauth.AllauthConfig.ALLAUTH_ENABLED
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.ALLAUTH_ENABLED
```

````

````{py:attribute} REGISTRATION_ENABLED
:canonical: archivebox.config.allauth.AllauthConfig.REGISTRATION_ENABLED
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.REGISTRATION_ENABLED
```

````

````{py:attribute} REGISTRATION_MODE
:canonical: archivebox.config.allauth.AllauthConfig.REGISTRATION_MODE
:type: typing.Literal[_io.open, approval]
:value: >
   'approval'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.REGISTRATION_MODE
```

````

````{py:attribute} EMAIL_VERIFICATION
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_VERIFICATION
:type: typing.Literal[none, optional, mandatory]
:value: >
   'none'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_VERIFICATION
```

````

````{py:attribute} SOCIALACCOUNT_PROVIDERS
:canonical: archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_PROVIDERS
:type: dict
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_PROVIDERS
```

````

````{py:attribute} SOCIALACCOUNT_EMAIL_AUTHENTICATION
:canonical: archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_EMAIL_AUTHENTICATION
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_EMAIL_AUTHENTICATION
```

````

````{py:attribute} SOCIALACCOUNT_EMAIL_AUTO_CONNECT
:canonical: archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_EMAIL_AUTO_CONNECT
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.SOCIALACCOUNT_EMAIL_AUTO_CONNECT
```

````

````{py:attribute} EMAIL_HOST
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_HOST
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_HOST
```

````

````{py:attribute} EMAIL_PORT
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_PORT
:type: int
:value: >
   587

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_PORT
```

````

````{py:attribute} EMAIL_HOST_USER
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_HOST_USER
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_HOST_USER
```

````

````{py:attribute} EMAIL_HOST_PASSWORD
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_HOST_PASSWORD
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_HOST_PASSWORD
```

````

````{py:attribute} EMAIL_USE_TLS
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_USE_TLS
:type: bool
:value: >
   True

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_USE_TLS
```

````

````{py:attribute} EMAIL_USE_SSL
:canonical: archivebox.config.allauth.AllauthConfig.EMAIL_USE_SSL
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.EMAIL_USE_SSL
```

````

````{py:attribute} DEFAULT_FROM_EMAIL
:canonical: archivebox.config.allauth.AllauthConfig.DEFAULT_FROM_EMAIL
:type: str
:value: >
   'webmaster@localhost'

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.DEFAULT_FROM_EMAIL
```

````

````{py:method} validate_email_linking() -> typing.Self
:canonical: archivebox.config.allauth.AllauthConfig.validate_email_linking

```{autodoc2-docstring} archivebox.config.allauth.AllauthConfig.validate_email_linking
```

````

`````
