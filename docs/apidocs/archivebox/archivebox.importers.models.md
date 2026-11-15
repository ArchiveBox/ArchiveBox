# {py:mod}`archivebox.importers.models`

```{py:module} archivebox.importers.models
```

```{autodoc2-docstring} archivebox.importers.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ImporterQuerySet <archivebox.importers.models.ImporterQuerySet>`
  - ```{autodoc2-docstring} archivebox.importers.models.ImporterQuerySet
    :summary:
    ```
* - {py:obj}`ImporterSource <archivebox.importers.models.ImporterSource>`
  - ```{autodoc2-docstring} archivebox.importers.models.ImporterSource
    :summary:
    ```
* - {py:obj}`ImporterRun <archivebox.importers.models.ImporterRun>`
  - ```{autodoc2-docstring} archivebox.importers.models.ImporterRun
    :summary:
    ```
````

### API

`````{py:class} ImporterQuerySet
:canonical: archivebox.importers.models.ImporterQuerySet

Bases: {py:obj}`django.db.models.QuerySet`

```{autodoc2-docstring} archivebox.importers.models.ImporterQuerySet
```

````{py:method} update(**kwargs)
:canonical: archivebox.importers.models.ImporterQuerySet.update

```{autodoc2-docstring} archivebox.importers.models.ImporterQuerySet.update
```

````

`````

``````{py:class} ImporterSource
:canonical: archivebox.importers.models.ImporterSource

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.importers.models.ImporterSource
```

````{py:attribute} objects
:canonical: archivebox.importers.models.ImporterSource.objects
:value: >
   'as_manager(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.objects
```

````

````{py:attribute} emoji
:canonical: archivebox.importers.models.ImporterSource.emoji
:type: str
:value: >
   '📥'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.emoji
```

````

````{py:attribute} id
:canonical: archivebox.importers.models.ImporterSource.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.id
```

````

````{py:attribute} created_at
:canonical: archivebox.importers.models.ImporterSource.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.created_at
```

````

````{py:attribute} created_by
:canonical: archivebox.importers.models.ImporterSource.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.created_by
```

````

````{py:attribute} name
:canonical: archivebox.importers.models.ImporterSource.name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.name
```

````

````{py:attribute} plugin
:canonical: archivebox.importers.models.ImporterSource.plugin
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.plugin
```

````

````{py:attribute} feed
:canonical: archivebox.importers.models.ImporterSource.feed
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.feed
```

````

````{py:attribute} persona
:canonical: archivebox.importers.models.ImporterSource.persona
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.persona
```

````

````{py:attribute} folder
:canonical: archivebox.importers.models.ImporterSource.folder
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.folder
```

````

````{py:attribute} settings
:canonical: archivebox.importers.models.ImporterSource.settings
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.settings
```

````

````{py:attribute} checkpoint
:canonical: archivebox.importers.models.ImporterSource.checkpoint
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.checkpoint
```

````

````{py:attribute} account
:canonical: archivebox.importers.models.ImporterSource.account
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.account
```

````

````{py:attribute} limit
:canonical: archivebox.importers.models.ImporterSource.limit
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.limit
```

````

````{py:attribute} tags
:canonical: archivebox.importers.models.ImporterSource.tags
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.tags
```

````

````{py:attribute} schedule
:canonical: archivebox.importers.models.ImporterSource.schedule
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.schedule
```

````

````{py:attribute} enabled
:canonical: archivebox.importers.models.ImporterSource.enabled
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.enabled
```

````

````{py:attribute} next_run_at
:canonical: archivebox.importers.models.ImporterSource.next_run_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.next_run_at
```

````

`````{py:class} Meta
:canonical: archivebox.importers.models.ImporterSource.Meta

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.Meta
```

````{py:attribute} ordering
:canonical: archivebox.importers.models.ImporterSource.Meta.ordering
:type: typing.ClassVar
:value: >
   ['name', 'id']

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.Meta.ordering
```

````

`````

````{py:method} __str__()
:canonical: archivebox.importers.models.ImporterSource.__str__

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.__str__
```

````

````{py:method} to_json()
:canonical: archivebox.importers.models.ImporterSource.to_json

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.to_json
```

````

````{py:method} get_absolute_url()
:canonical: archivebox.importers.models.ImporterSource.get_absolute_url

```{autodoc2-docstring} archivebox.importers.models.ImporterSource.get_absolute_url
```

````

``````

``````{py:class} ImporterRun
:canonical: archivebox.importers.models.ImporterRun

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.importers.models.ImporterRun
```

````{py:attribute} objects
:canonical: archivebox.importers.models.ImporterRun.objects
:value: >
   'as_manager(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.objects
```

````

````{py:attribute} emoji
:canonical: archivebox.importers.models.ImporterRun.emoji
:type: str
:value: >
   '🔄'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.emoji
```

````

`````{py:class} Status
:canonical: archivebox.importers.models.ImporterRun.Status

Bases: {py:obj}`django.db.models.TextChoices`

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status
```

````{py:attribute} QUEUED
:canonical: archivebox.importers.models.ImporterRun.Status.QUEUED
:value: >
   ('queued', 'Queued')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.QUEUED
```

````

````{py:attribute} RUNNING
:canonical: archivebox.importers.models.ImporterRun.Status.RUNNING
:value: >
   ('running', 'Running')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.RUNNING
```

````

````{py:attribute} SUCCEEDED
:canonical: archivebox.importers.models.ImporterRun.Status.SUCCEEDED
:value: >
   ('succeeded', 'Succeeded')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.SUCCEEDED
```

````

````{py:attribute} FAILED
:canonical: archivebox.importers.models.ImporterRun.Status.FAILED
:value: >
   ('failed', 'Failed')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.FAILED
```

````

````{py:attribute} NEEDS_LOGIN
:canonical: archivebox.importers.models.ImporterRun.Status.NEEDS_LOGIN
:value: >
   ('needs_login', 'Needs login')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.NEEDS_LOGIN
```

````

````{py:attribute} CANCELLED
:canonical: archivebox.importers.models.ImporterRun.Status.CANCELLED
:value: >
   ('cancelled', 'Cancelled')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Status.CANCELLED
```

````

`````

`````{py:class} Action
:canonical: archivebox.importers.models.ImporterRun.Action

Bases: {py:obj}`django.db.models.TextChoices`

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Action
```

````{py:attribute} CHECK
:canonical: archivebox.importers.models.ImporterRun.Action.CHECK
:value: >
   ('check', 'Check access')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Action.CHECK
```

````

````{py:attribute} PREVIEW
:canonical: archivebox.importers.models.ImporterRun.Action.PREVIEW
:value: >
   ('preview', 'Preview')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Action.PREVIEW
```

````

````{py:attribute} IMPORT
:canonical: archivebox.importers.models.ImporterRun.Action.IMPORT
:value: >
   ('import', 'Import')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Action.IMPORT
```

````

````{py:attribute} RESET_CODE
:canonical: archivebox.importers.models.ImporterRun.Action.RESET_CODE
:value: >
   ('reset_code', 'Reset learned code')

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Action.RESET_CODE
```

````

`````

````{py:attribute} id
:canonical: archivebox.importers.models.ImporterRun.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.id
```

````

````{py:attribute} source
:canonical: archivebox.importers.models.ImporterRun.source
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.source
```

````

````{py:attribute} created_at
:canonical: archivebox.importers.models.ImporterRun.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.created_at
```

````

````{py:attribute} started_at
:canonical: archivebox.importers.models.ImporterRun.started_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.started_at
```

````

````{py:attribute} finished_at
:canonical: archivebox.importers.models.ImporterRun.finished_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.finished_at
```

````

````{py:attribute} action
:canonical: archivebox.importers.models.ImporterRun.action
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.action
```

````

````{py:attribute} status
:canonical: archivebox.importers.models.ImporterRun.status
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.status
```

````

````{py:attribute} cancel_requested
:canonical: archivebox.importers.models.ImporterRun.cancel_requested
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.cancel_requested
```

````

````{py:attribute} owner
:canonical: archivebox.importers.models.ImporterRun.owner
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.owner
```

````

````{py:attribute} crawl
:canonical: archivebox.importers.models.ImporterRun.crawl
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.crawl
```

````

````{py:attribute} request
:canonical: archivebox.importers.models.ImporterRun.request
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.request
```

````

````{py:attribute} items
:canonical: archivebox.importers.models.ImporterRun.items
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.items
```

````

````{py:attribute} result
:canonical: archivebox.importers.models.ImporterRun.result
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.result
```

````

````{py:attribute} message
:canonical: archivebox.importers.models.ImporterRun.message
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.message
```

````

````{py:method} to_json()
:canonical: archivebox.importers.models.ImporterRun.to_json

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.to_json
```

````

````{py:property} status_message
:canonical: archivebox.importers.models.ImporterRun.status_message

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.status_message
```

````

`````{py:class} Meta
:canonical: archivebox.importers.models.ImporterRun.Meta

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Meta
```

````{py:attribute} ordering
:canonical: archivebox.importers.models.ImporterRun.Meta.ordering
:type: typing.ClassVar
:value: >
   ['-created_at', '-id']

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Meta.ordering
```

````

````{py:attribute} constraints
:canonical: archivebox.importers.models.ImporterRun.Meta.constraints
:type: typing.ClassVar
:value: >
   None

```{autodoc2-docstring} archivebox.importers.models.ImporterRun.Meta.constraints
```

````

`````

``````
