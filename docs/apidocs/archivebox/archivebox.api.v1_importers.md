# {py:mod}`archivebox.api.v1_importers`

```{py:module} archivebox.api.v1_importers
```

```{autodoc2-docstring} archivebox.api.v1_importers
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SourceSchema <archivebox.api.v1_importers.SourceSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema
    :summary:
    ```
* - {py:obj}`RunSchema <archivebox.api.v1_importers.RunSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema
    :summary:
    ```
* - {py:obj}`SourceCreate <archivebox.api.v1_importers.SourceCreate>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate
    :summary:
    ```
* - {py:obj}`SourceUpdate <archivebox.api.v1_importers.SourceUpdate>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`importer_catalog <archivebox.api.v1_importers.importer_catalog>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.importer_catalog
    :summary:
    ```
* - {py:obj}`list_sources <archivebox.api.v1_importers.list_sources>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.list_sources
    :summary:
    ```
* - {py:obj}`create_source <archivebox.api.v1_importers.create_source>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.create_source
    :summary:
    ```
* - {py:obj}`get_source <archivebox.api.v1_importers.get_source>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.get_source
    :summary:
    ```
* - {py:obj}`update_source <archivebox.api.v1_importers.update_source>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.update_source
    :summary:
    ```
* - {py:obj}`remove_source <archivebox.api.v1_importers.remove_source>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.remove_source
    :summary:
    ```
* - {py:obj}`run_source_action <archivebox.api.v1_importers.run_source_action>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.run_source_action
    :summary:
    ```
* - {py:obj}`list_runs <archivebox.api.v1_importers.list_runs>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.list_runs
    :summary:
    ```
* - {py:obj}`get_run <archivebox.api.v1_importers.get_run>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.get_run
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_importers.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_importers.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_importers.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_importers.router
```

````

`````{py:class} SourceSchema
:canonical: archivebox.api.v1_importers.SourceSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema
```

````{py:attribute} type
:canonical: archivebox.api.v1_importers.SourceSchema.type
:type: str
:value: >
   'ImporterSource'

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.type
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_importers.SourceSchema.id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_importers.SourceSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.name
```

````

````{py:attribute} plugin
:canonical: archivebox.api.v1_importers.SourceSchema.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.plugin
```

````

````{py:attribute} feed
:canonical: archivebox.api.v1_importers.SourceSchema.feed
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.feed
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_importers.SourceSchema.created_by_id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_importers.SourceSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.created_by_username
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_importers.SourceSchema.created_at
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.created_at
```

````

````{py:attribute} persona_id
:canonical: archivebox.api.v1_importers.SourceSchema.persona_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.persona_id
```

````

````{py:attribute} persona_name
:canonical: archivebox.api.v1_importers.SourceSchema.persona_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.persona_name
```

````

````{py:attribute} folder_id
:canonical: archivebox.api.v1_importers.SourceSchema.folder_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.folder_id
```

````

````{py:attribute} folder_name
:canonical: archivebox.api.v1_importers.SourceSchema.folder_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.folder_name
```

````

````{py:attribute} settings
:canonical: archivebox.api.v1_importers.SourceSchema.settings
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.settings
```

````

````{py:attribute} checkpoint
:canonical: archivebox.api.v1_importers.SourceSchema.checkpoint
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.checkpoint
```

````

````{py:attribute} account
:canonical: archivebox.api.v1_importers.SourceSchema.account
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.account
```

````

````{py:attribute} limit
:canonical: archivebox.api.v1_importers.SourceSchema.limit
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.limit
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_importers.SourceSchema.tags
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.tags
```

````

````{py:attribute} schedule
:canonical: archivebox.api.v1_importers.SourceSchema.schedule
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.schedule
```

````

````{py:attribute} enabled
:canonical: archivebox.api.v1_importers.SourceSchema.enabled
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.enabled
```

````

````{py:attribute} next_run_at
:canonical: archivebox.api.v1_importers.SourceSchema.next_run_at
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceSchema.next_run_at
```

````

`````

`````{py:class} RunSchema
:canonical: archivebox.api.v1_importers.RunSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema
```

````{py:attribute} type
:canonical: archivebox.api.v1_importers.RunSchema.type
:type: str
:value: >
   'ImporterRun'

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.type
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_importers.RunSchema.id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.id
```

````

````{py:attribute} source_id
:canonical: archivebox.api.v1_importers.RunSchema.source_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.source_id
```

````

````{py:attribute} source_name
:canonical: archivebox.api.v1_importers.RunSchema.source_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.source_name
```

````

````{py:attribute} action
:canonical: archivebox.api.v1_importers.RunSchema.action
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.action
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_importers.RunSchema.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.status
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_importers.RunSchema.created_at
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.created_at
```

````

````{py:attribute} started_at
:canonical: archivebox.api.v1_importers.RunSchema.started_at
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.started_at
```

````

````{py:attribute} finished_at
:canonical: archivebox.api.v1_importers.RunSchema.finished_at
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.finished_at
```

````

````{py:attribute} owner_id
:canonical: archivebox.api.v1_importers.RunSchema.owner_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.owner_id
```

````

````{py:attribute} crawl_id
:canonical: archivebox.api.v1_importers.RunSchema.crawl_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.crawl_id
```

````

````{py:attribute} cancel_requested
:canonical: archivebox.api.v1_importers.RunSchema.cancel_requested
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.cancel_requested
```

````

````{py:attribute} items
:canonical: archivebox.api.v1_importers.RunSchema.items
:type: list
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.items
```

````

````{py:attribute} result
:canonical: archivebox.api.v1_importers.RunSchema.result
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.result
```

````

````{py:attribute} message
:canonical: archivebox.api.v1_importers.RunSchema.message
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.RunSchema.message
```

````

`````

`````{py:class} SourceCreate
:canonical: archivebox.api.v1_importers.SourceCreate

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate
```

````{py:attribute} plugin
:canonical: archivebox.api.v1_importers.SourceCreate.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.plugin
```

````

````{py:attribute} feed
:canonical: archivebox.api.v1_importers.SourceCreate.feed
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.feed
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_importers.SourceCreate.name
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.name
```

````

````{py:attribute} persona_id
:canonical: archivebox.api.v1_importers.SourceCreate.persona_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.persona_id
```

````

````{py:attribute} folder_id
:canonical: archivebox.api.v1_importers.SourceCreate.folder_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.folder_id
```

````

````{py:attribute} settings
:canonical: archivebox.api.v1_importers.SourceCreate.settings
:type: dict
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.settings
```

````

````{py:attribute} limit
:canonical: archivebox.api.v1_importers.SourceCreate.limit
:type: int
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.limit
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_importers.SourceCreate.tags
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.tags
```

````

````{py:attribute} schedule
:canonical: archivebox.api.v1_importers.SourceCreate.schedule
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.schedule
```

````

````{py:attribute} enabled
:canonical: archivebox.api.v1_importers.SourceCreate.enabled
:type: bool
:value: >
   True

```{autodoc2-docstring} archivebox.api.v1_importers.SourceCreate.enabled
```

````

`````

`````{py:class} SourceUpdate
:canonical: archivebox.api.v1_importers.SourceUpdate

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate
```

````{py:attribute} name
:canonical: archivebox.api.v1_importers.SourceUpdate.name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.name
```

````

````{py:attribute} persona_id
:canonical: archivebox.api.v1_importers.SourceUpdate.persona_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.persona_id
```

````

````{py:attribute} folder_id
:canonical: archivebox.api.v1_importers.SourceUpdate.folder_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.folder_id
```

````

````{py:attribute} settings
:canonical: archivebox.api.v1_importers.SourceUpdate.settings
:type: dict | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.settings
```

````

````{py:attribute} limit
:canonical: archivebox.api.v1_importers.SourceUpdate.limit
:type: int | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.limit
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_importers.SourceUpdate.tags
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.tags
```

````

````{py:attribute} schedule
:canonical: archivebox.api.v1_importers.SourceUpdate.schedule
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.schedule
```

````

````{py:attribute} enabled
:canonical: archivebox.api.v1_importers.SourceUpdate.enabled
:type: bool | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_importers.SourceUpdate.enabled
```

````

`````

````{py:function} importer_catalog(request)
:canonical: archivebox.api.v1_importers.importer_catalog

```{autodoc2-docstring} archivebox.api.v1_importers.importer_catalog
```
````

````{py:function} list_sources(request, format: str | None = None)
:canonical: archivebox.api.v1_importers.list_sources

```{autodoc2-docstring} archivebox.api.v1_importers.list_sources
```
````

````{py:function} create_source(request, data: archivebox.api.v1_importers.SourceCreate)
:canonical: archivebox.api.v1_importers.create_source

```{autodoc2-docstring} archivebox.api.v1_importers.create_source
```
````

````{py:function} get_source(request, source_id: uuid.UUID)
:canonical: archivebox.api.v1_importers.get_source

```{autodoc2-docstring} archivebox.api.v1_importers.get_source
```
````

````{py:function} update_source(request, source_id: uuid.UUID, data: archivebox.api.v1_importers.SourceUpdate)
:canonical: archivebox.api.v1_importers.update_source

```{autodoc2-docstring} archivebox.api.v1_importers.update_source
```
````

````{py:function} remove_source(request, source_id: uuid.UUID)
:canonical: archivebox.api.v1_importers.remove_source

```{autodoc2-docstring} archivebox.api.v1_importers.remove_source
```
````

````{py:function} run_source_action(request, source_id: uuid.UUID, action: typing.Literal[check, preview, import, pause, resume, reset, reset_code])
:canonical: archivebox.api.v1_importers.run_source_action

```{autodoc2-docstring} archivebox.api.v1_importers.run_source_action
```
````

````{py:function} list_runs(request, source_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0, format: str | None = None)
:canonical: archivebox.api.v1_importers.list_runs

```{autodoc2-docstring} archivebox.api.v1_importers.list_runs
```
````

````{py:function} get_run(request, run_id: uuid.UUID)
:canonical: archivebox.api.v1_importers.get_run

```{autodoc2-docstring} archivebox.api.v1_importers.get_run
```
````
