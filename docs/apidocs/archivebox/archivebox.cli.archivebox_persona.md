# {py:mod}`archivebox.cli.archivebox_persona`

```{py:module} archivebox.cli.archivebox_persona
```

```{autodoc2-docstring} archivebox.cli.archivebox_persona
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_chrome_user_data_dir <archivebox.cli.archivebox_persona.get_chrome_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_chrome_user_data_dir
    :summary:
    ```
* - {py:obj}`get_brave_user_data_dir <archivebox.cli.archivebox_persona.get_brave_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_brave_user_data_dir
    :summary:
    ```
* - {py:obj}`get_edge_user_data_dir <archivebox.cli.archivebox_persona.get_edge_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_edge_user_data_dir
    :summary:
    ```
* - {py:obj}`validate_persona_name <archivebox.cli.archivebox_persona.validate_persona_name>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.validate_persona_name
    :summary:
    ```
* - {py:obj}`ensure_path_within_personas_dir <archivebox.cli.archivebox_persona.ensure_path_within_personas_dir>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.ensure_path_within_personas_dir
    :summary:
    ```
* - {py:obj}`create_personas <archivebox.cli.archivebox_persona.create_personas>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.create_personas
    :summary:
    ```
* - {py:obj}`list_personas <archivebox.cli.archivebox_persona.list_personas>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.list_personas
    :summary:
    ```
* - {py:obj}`update_personas <archivebox.cli.archivebox_persona.update_personas>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.update_personas
    :summary:
    ```
* - {py:obj}`delete_personas <archivebox.cli.archivebox_persona.delete_personas>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.delete_personas
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_persona.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.main
    :summary:
    ```
* - {py:obj}`create_cmd <archivebox.cli.archivebox_persona.create_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.create_cmd
    :summary:
    ```
* - {py:obj}`list_cmd <archivebox.cli.archivebox_persona.list_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.list_cmd
    :summary:
    ```
* - {py:obj}`update_cmd <archivebox.cli.archivebox_persona.update_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.update_cmd
    :summary:
    ```
* - {py:obj}`delete_cmd <archivebox.cli.archivebox_persona.delete_cmd>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.delete_cmd
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__command__ <archivebox.cli.archivebox_persona.__command__>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.__command__
    :summary:
    ```
* - {py:obj}`BROWSER_PROFILE_FINDERS <archivebox.cli.archivebox_persona.BROWSER_PROFILE_FINDERS>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.BROWSER_PROFILE_FINDERS
    :summary:
    ```
* - {py:obj}`CHROMIUM_BROWSERS <archivebox.cli.archivebox_persona.CHROMIUM_BROWSERS>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_persona.CHROMIUM_BROWSERS
    :summary:
    ```
````

### API

````{py:data} __command__
:canonical: archivebox.cli.archivebox_persona.__command__
:value: >
   'archivebox persona'

```{autodoc2-docstring} archivebox.cli.archivebox_persona.__command__
```

````

````{py:function} get_chrome_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.cli.archivebox_persona.get_chrome_user_data_dir

```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_chrome_user_data_dir
```
````

````{py:function} get_brave_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.cli.archivebox_persona.get_brave_user_data_dir

```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_brave_user_data_dir
```
````

````{py:function} get_edge_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.cli.archivebox_persona.get_edge_user_data_dir

```{autodoc2-docstring} archivebox.cli.archivebox_persona.get_edge_user_data_dir
```
````

````{py:data} BROWSER_PROFILE_FINDERS
:canonical: archivebox.cli.archivebox_persona.BROWSER_PROFILE_FINDERS
:value: >
   None

```{autodoc2-docstring} archivebox.cli.archivebox_persona.BROWSER_PROFILE_FINDERS
```

````

````{py:data} CHROMIUM_BROWSERS
:canonical: archivebox.cli.archivebox_persona.CHROMIUM_BROWSERS
:value: >
   None

```{autodoc2-docstring} archivebox.cli.archivebox_persona.CHROMIUM_BROWSERS
```

````

````{py:function} validate_persona_name(name: str) -> tuple[bool, str]
:canonical: archivebox.cli.archivebox_persona.validate_persona_name

```{autodoc2-docstring} archivebox.cli.archivebox_persona.validate_persona_name
```
````

````{py:function} ensure_path_within_personas_dir(persona_path: pathlib.Path) -> bool
:canonical: archivebox.cli.archivebox_persona.ensure_path_within_personas_dir

```{autodoc2-docstring} archivebox.cli.archivebox_persona.ensure_path_within_personas_dir
```
````

````{py:function} create_personas(names: collections.abc.Iterable[str], import_from: str | None = None, profile: str | None = None) -> int
:canonical: archivebox.cli.archivebox_persona.create_personas

```{autodoc2-docstring} archivebox.cli.archivebox_persona.create_personas
```
````

````{py:function} list_personas(name: str | None = None, name__icontains: str | None = None, limit: int | None = None) -> int
:canonical: archivebox.cli.archivebox_persona.list_personas

```{autodoc2-docstring} archivebox.cli.archivebox_persona.list_personas
```
````

````{py:function} update_personas(name: str | None = None) -> int
:canonical: archivebox.cli.archivebox_persona.update_personas

```{autodoc2-docstring} archivebox.cli.archivebox_persona.update_personas
```
````

````{py:function} delete_personas(yes: bool = False, dry_run: bool = False) -> int
:canonical: archivebox.cli.archivebox_persona.delete_personas

```{autodoc2-docstring} archivebox.cli.archivebox_persona.delete_personas
```
````

````{py:function} main()
:canonical: archivebox.cli.archivebox_persona.main

```{autodoc2-docstring} archivebox.cli.archivebox_persona.main
```
````

````{py:function} create_cmd(names: tuple, import_from: str | None, profile: str | None)
:canonical: archivebox.cli.archivebox_persona.create_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_persona.create_cmd
```
````

````{py:function} list_cmd(name: str | None, name__icontains: str | None, limit: int | None)
:canonical: archivebox.cli.archivebox_persona.list_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_persona.list_cmd
```
````

````{py:function} update_cmd(name: str | None)
:canonical: archivebox.cli.archivebox_persona.update_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_persona.update_cmd
```
````

````{py:function} delete_cmd(yes: bool, dry_run: bool)
:canonical: archivebox.cli.archivebox_persona.delete_cmd

```{autodoc2-docstring} archivebox.cli.archivebox_persona.delete_cmd
```
````
