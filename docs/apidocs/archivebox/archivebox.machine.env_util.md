# {py:mod}`archivebox.machine.env_util`

```{py:module} archivebox.machine.env_util
```

```{autodoc2-docstring} archivebox.machine.env_util
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`stringify_env_value <archivebox.machine.env_util.stringify_env_value>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.stringify_env_value
    :summary:
    ```
* - {py:obj}`is_redacted_env_key <archivebox.machine.env_util.is_redacted_env_key>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.is_redacted_env_key
    :summary:
    ```
* - {py:obj}`redact_env <archivebox.machine.env_util.redact_env>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.redact_env
    :summary:
    ```
* - {py:obj}`env_to_dotenv_text <archivebox.machine.env_util.env_to_dotenv_text>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.env_to_dotenv_text
    :summary:
    ```
* - {py:obj}`env_to_shell_exports <archivebox.machine.env_util.env_to_shell_exports>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.env_to_shell_exports
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SENSITIVE_ENV_KEY_PARTS <archivebox.machine.env_util.SENSITIVE_ENV_KEY_PARTS>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.SENSITIVE_ENV_KEY_PARTS
    :summary:
    ```
* - {py:obj}`SHELL_ENV_KEY_RE <archivebox.machine.env_util.SHELL_ENV_KEY_RE>`
  - ```{autodoc2-docstring} archivebox.machine.env_util.SHELL_ENV_KEY_RE
    :summary:
    ```
````

### API

````{py:data} SENSITIVE_ENV_KEY_PARTS
:canonical: archivebox.machine.env_util.SENSITIVE_ENV_KEY_PARTS
:value: >
   ('KEY', 'TOKEN', 'SECRET')

```{autodoc2-docstring} archivebox.machine.env_util.SENSITIVE_ENV_KEY_PARTS
```

````

````{py:data} SHELL_ENV_KEY_RE
:canonical: archivebox.machine.env_util.SHELL_ENV_KEY_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.machine.env_util.SHELL_ENV_KEY_RE
```

````

````{py:function} stringify_env_value(value: typing.Any) -> str
:canonical: archivebox.machine.env_util.stringify_env_value

```{autodoc2-docstring} archivebox.machine.env_util.stringify_env_value
```
````

````{py:function} is_redacted_env_key(key: str) -> bool
:canonical: archivebox.machine.env_util.is_redacted_env_key

```{autodoc2-docstring} archivebox.machine.env_util.is_redacted_env_key
```
````

````{py:function} redact_env(env: dict[str, typing.Any] | None) -> dict[str, typing.Any]
:canonical: archivebox.machine.env_util.redact_env

```{autodoc2-docstring} archivebox.machine.env_util.redact_env
```
````

````{py:function} env_to_dotenv_text(env: dict[str, typing.Any] | None) -> str
:canonical: archivebox.machine.env_util.env_to_dotenv_text

```{autodoc2-docstring} archivebox.machine.env_util.env_to_dotenv_text
```
````

````{py:function} env_to_shell_exports(env: dict[str, typing.Any] | None) -> str
:canonical: archivebox.machine.env_util.env_to_shell_exports

```{autodoc2-docstring} archivebox.machine.env_util.env_to_shell_exports
```
````
