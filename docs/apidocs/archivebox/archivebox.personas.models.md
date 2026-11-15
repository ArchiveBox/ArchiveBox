# {py:mod}`archivebox.personas.models`

```{py:module} archivebox.personas.models
```

```{autodoc2-docstring} archivebox.personas.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Persona <archivebox.personas.models.Persona>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`derive_persona_config <archivebox.personas.models.derive_persona_config>`
  - ```{autodoc2-docstring} archivebox.personas.models.derive_persona_config
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_fcntl <archivebox.personas.models._fcntl>`
  - ```{autodoc2-docstring} archivebox.personas.models._fcntl
    :summary:
    ```
````

### API

````{py:data} _fcntl
:canonical: archivebox.personas.models._fcntl
:type: typing.Any | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.models._fcntl
```

````

````{py:function} derive_persona_config(*, name: str, config: collections.abc.Mapping[str, typing.Any] | None, persona_dir: pathlib.Path) -> dict[str, typing.Any]
:canonical: archivebox.personas.models.derive_persona_config

```{autodoc2-docstring} archivebox.personas.models.derive_persona_config
```
````

``````{py:class} Persona
:canonical: archivebox.personas.models.Persona

Bases: {py:obj}`archivebox.base_models.models.ModelWithConfig`

````{py:attribute} emoji
:canonical: archivebox.personas.models.Persona.emoji
:type: str
:value: >
   '🎭'

```{autodoc2-docstring} archivebox.personas.models.Persona.emoji
```

````

````{py:attribute} id
:canonical: archivebox.personas.models.Persona.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.personas.models.Persona.id
```

````

````{py:attribute} name
:canonical: archivebox.personas.models.Persona.name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.personas.models.Persona.name
```

````

````{py:attribute} created_at
:canonical: archivebox.personas.models.Persona.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.personas.models.Persona.created_at
```

````

````{py:attribute} created_by
:canonical: archivebox.personas.models.Persona.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.personas.models.Persona.created_by
```

````

````{py:attribute} permissions
:canonical: archivebox.personas.models.Persona.permissions
:value: >
   'GeneratedField(...)'

```{autodoc2-docstring} archivebox.personas.models.Persona.permissions
```

````

`````{py:class} Meta
:canonical: archivebox.personas.models.Persona.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithConfig.Meta`

```{autodoc2-docstring} archivebox.personas.models.Persona.Meta
```

````{py:attribute} app_label
:canonical: archivebox.personas.models.Persona.Meta.app_label
:value: >
   'personas'

```{autodoc2-docstring} archivebox.personas.models.Persona.Meta.app_label
```

````

`````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.personas.models.Persona.save

```{autodoc2-docstring} archivebox.personas.models.Persona.save
```

````

````{py:method} __str__() -> str
:canonical: archivebox.personas.models.Persona.__str__

```{autodoc2-docstring} archivebox.personas.models.Persona.__str__
```

````

````{py:property} path
:canonical: archivebox.personas.models.Persona.path
:type: pathlib.Path

```{autodoc2-docstring} archivebox.personas.models.Persona.path
```

````

````{py:method} directory_name(name: str) -> str
:canonical: archivebox.personas.models.Persona.directory_name
:staticmethod:

```{autodoc2-docstring} archivebox.personas.models.Persona.directory_name
```

````

````{py:method} find_named(name: str) -> Persona | None
:canonical: archivebox.personas.models.Persona.find_named
:classmethod:

```{autodoc2-docstring} archivebox.personas.models.Persona.find_named
```

````

````{py:method} validate_name(name: str) -> str
:canonical: archivebox.personas.models.Persona.validate_name

```{autodoc2-docstring} archivebox.personas.models.Persona.validate_name
```

````

````{py:property} CHROME_USER_DATA_DIR
:canonical: archivebox.personas.models.Persona.CHROME_USER_DATA_DIR
:type: str

```{autodoc2-docstring} archivebox.personas.models.Persona.CHROME_USER_DATA_DIR
```

````

````{py:property} CHROME_DOWNLOADS_DIR
:canonical: archivebox.personas.models.Persona.CHROME_DOWNLOADS_DIR
:type: str

```{autodoc2-docstring} archivebox.personas.models.Persona.CHROME_DOWNLOADS_DIR
```

````

````{py:property} COOKIES_FILE
:canonical: archivebox.personas.models.Persona.COOKIES_FILE
:type: str

```{autodoc2-docstring} archivebox.personas.models.Persona.COOKIES_FILE
```

````

````{py:property} AUTH_STORAGE_FILE
:canonical: archivebox.personas.models.Persona.AUTH_STORAGE_FILE
:type: str

```{autodoc2-docstring} archivebox.personas.models.Persona.AUTH_STORAGE_FILE
```

````

````{py:method} get_derived_config() -> dict
:canonical: archivebox.personas.models.Persona.get_derived_config

```{autodoc2-docstring} archivebox.personas.models.Persona.get_derived_config
```

````

````{py:method} ensure_dirs() -> None
:canonical: archivebox.personas.models.Persona.ensure_dirs

```{autodoc2-docstring} archivebox.personas.models.Persona.ensure_dirs
```

````

````{py:method} lock_runtime_for_crawl()
:canonical: archivebox.personas.models.Persona.lock_runtime_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.lock_runtime_for_crawl
```

````

````{py:method} get_or_create_named(name: str, *, defaults: dict | None = None) -> archivebox.personas.models.Persona
:canonical: archivebox.personas.models.Persona.get_or_create_named
:classmethod:

```{autodoc2-docstring} archivebox.personas.models.Persona.get_or_create_named
```

````

````{py:method} runtime_root_for_crawl(crawl) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_root_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_root_for_crawl
```

````

````{py:method} local_runtime_root_for_crawl(crawl) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.local_runtime_root_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.local_runtime_root_for_crawl
```

````

````{py:method} runtime_profile_dir_for_crawl(crawl) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_profile_dir_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_profile_dir_for_crawl
```

````

````{py:method} runtime_downloads_dir_for_crawl(crawl) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_downloads_dir_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_downloads_dir_for_crawl
```

````

````{py:method} runtime_root_for_snapshot(snapshot) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_root_for_snapshot

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_root_for_snapshot
```

````

````{py:method} runtime_profile_dir_for_snapshot(snapshot) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_profile_dir_for_snapshot

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_profile_dir_for_snapshot
```

````

````{py:method} runtime_downloads_dir_for_snapshot(snapshot) -> pathlib.Path
:canonical: archivebox.personas.models.Persona.runtime_downloads_dir_for_snapshot

```{autodoc2-docstring} archivebox.personas.models.Persona.runtime_downloads_dir_for_snapshot
```

````

````{py:method} link_runtime_for_output(output_dir: pathlib.Path, runtime_root: pathlib.Path) -> None
:canonical: archivebox.personas.models.Persona.link_runtime_for_output

```{autodoc2-docstring} archivebox.personas.models.Persona.link_runtime_for_output
```

````

````{py:method} prepare_runtime_for_crawl(crawl, chrome_binary: str = '', *, use_template: bool = True) -> dict[str, str]
:canonical: archivebox.personas.models.Persona.prepare_runtime_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.prepare_runtime_for_crawl
```

````

````{py:method} prepare_runtime_for_snapshot(snapshot, chrome_binary: str = '', *, local_root: pathlib.Path | None = None, use_template: bool = True) -> dict[str, str]
:canonical: archivebox.personas.models.Persona.prepare_runtime_for_snapshot

```{autodoc2-docstring} archivebox.personas.models.Persona.prepare_runtime_for_snapshot
```

````

````{py:method} cleanup_runtime_for_crawl(crawl) -> None
:canonical: archivebox.personas.models.Persona.cleanup_runtime_for_crawl

```{autodoc2-docstring} archivebox.personas.models.Persona.cleanup_runtime_for_crawl
```

````

````{py:method} get_or_create_default() -> archivebox.personas.models.Persona
:canonical: archivebox.personas.models.Persona.get_or_create_default
:classmethod:

```{autodoc2-docstring} archivebox.personas.models.Persona.get_or_create_default
```

````

``````
