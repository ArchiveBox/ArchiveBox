# {py:mod}`archivebox.api.v1_personas`

```{py:module} archivebox.api.v1_personas
```

```{autodoc2-docstring} archivebox.api.v1_personas
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PersonaBrowserSettingsSchema <archivebox.api.v1_personas.PersonaBrowserSettingsSchema>`
  -
* - {py:obj}`PersonaSyncSchema <archivebox.api.v1_personas.PersonaSyncSchema>`
  -
* - {py:obj}`PersonaSchema <archivebox.api.v1_personas.PersonaSchema>`
  -
* - {py:obj}`PersonaSyncResponseSchema <archivebox.api.v1_personas.PersonaSyncResponseSchema>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`browser_settings_to_config <archivebox.api.v1_personas.browser_settings_to_config>`
  - ```{autodoc2-docstring} archivebox.api.v1_personas.browser_settings_to_config
    :summary:
    ```
* - {py:obj}`find_persona <archivebox.api.v1_personas.find_persona>`
  - ```{autodoc2-docstring} archivebox.api.v1_personas.find_persona
    :summary:
    ```
* - {py:obj}`get_personas <archivebox.api.v1_personas.get_personas>`
  - ```{autodoc2-docstring} archivebox.api.v1_personas.get_personas
    :summary:
    ```
* - {py:obj}`sync_persona <archivebox.api.v1_personas.sync_persona>`
  - ```{autodoc2-docstring} archivebox.api.v1_personas.sync_persona
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_personas.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_personas.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_personas.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_personas.router
```

````

`````{py:class} PersonaBrowserSettingsSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} user_agent
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.user_agent
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.user_agent
```

````

````{py:attribute} viewport_size
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.viewport_size
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.viewport_size
```

````

````{py:attribute} viewport_device_scale_factor
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.viewport_device_scale_factor
:type: float | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.viewport_device_scale_factor
```

````

````{py:attribute} language
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.language
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.language
```

````

````{py:attribute} timezone
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.timezone
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.timezone
```

````

````{py:attribute} geolocation
:canonical: archivebox.api.v1_personas.PersonaBrowserSettingsSchema.geolocation
:type: dict[str, typing.Any] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaBrowserSettingsSchema.geolocation
```

````

`````

`````{py:class} PersonaSyncSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_personas.PersonaSyncSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} extension_persona_id
:canonical: archivebox.api.v1_personas.PersonaSyncSchema.extension_persona_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncSchema.extension_persona_id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_personas.PersonaSyncSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncSchema.name
```

````

````{py:attribute} settings
:canonical: archivebox.api.v1_personas.PersonaSyncSchema.settings
:type: archivebox.api.v1_personas.PersonaBrowserSettingsSchema
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncSchema.settings
```

````

````{py:attribute} cookies_txt
:canonical: archivebox.api.v1_personas.PersonaSyncSchema.cookies_txt
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncSchema.cookies_txt
```

````

````{py:attribute} auth_json
:canonical: archivebox.api.v1_personas.PersonaSyncSchema.auth_json
:type: dict[str, typing.Any]
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncSchema.auth_json
```

````

`````

`````{py:class} PersonaSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_personas.PersonaSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_personas.PersonaSchema.TYPE
:type: str
:value: >
   'personas.models.Persona'

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_personas.PersonaSchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_personas.PersonaSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.name
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_personas.PersonaSchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.created_at
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_personas.PersonaSchema.created_by_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_personas.PersonaSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.created_by_username
```

````

````{py:attribute} config
:canonical: archivebox.api.v1_personas.PersonaSchema.config
:type: dict[str, typing.Any] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.config
```

````

````{py:method} resolve_created_by_id(obj)
:canonical: archivebox.api.v1_personas.PersonaSchema.resolve_created_by_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.resolve_created_by_id
```

````

````{py:method} resolve_created_by_username(obj) -> str
:canonical: archivebox.api.v1_personas.PersonaSchema.resolve_created_by_username
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.resolve_created_by_username
```

````

````{py:method} resolve_config(obj)
:canonical: archivebox.api.v1_personas.PersonaSchema.resolve_config
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSchema.resolve_config
```

````

`````

`````{py:class} PersonaSyncResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncResponseSchema.success
```

````

````{py:attribute} created
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema.created
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncResponseSchema.created
```

````

````{py:attribute} persona
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema.persona
:type: archivebox.api.v1_personas.PersonaSchema
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncResponseSchema.persona
```

````

````{py:attribute} cookies_file_written
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema.cookies_file_written
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncResponseSchema.cookies_file_written
```

````

````{py:attribute} auth_file_written
:canonical: archivebox.api.v1_personas.PersonaSyncResponseSchema.auth_file_written
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_personas.PersonaSyncResponseSchema.auth_file_written
```

````

`````

````{py:function} browser_settings_to_config(extension_persona_id: str, settings: archivebox.api.v1_personas.PersonaBrowserSettingsSchema) -> dict[str, typing.Any]
:canonical: archivebox.api.v1_personas.browser_settings_to_config

```{autodoc2-docstring} archivebox.api.v1_personas.browser_settings_to_config
```
````

````{py:function} find_persona(extension_persona_id: str, name: str) -> archivebox.personas.models.Persona | None
:canonical: archivebox.api.v1_personas.find_persona

```{autodoc2-docstring} archivebox.api.v1_personas.find_persona
```
````

````{py:function} get_personas(request: django.http.HttpRequest)
:canonical: archivebox.api.v1_personas.get_personas

```{autodoc2-docstring} archivebox.api.v1_personas.get_personas
```
````

````{py:function} sync_persona(request: django.http.HttpRequest, payload: archivebox.api.v1_personas.PersonaSyncSchema)
:canonical: archivebox.api.v1_personas.sync_persona

```{autodoc2-docstring} archivebox.api.v1_personas.sync_persona
```
````
