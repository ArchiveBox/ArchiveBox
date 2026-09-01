# {py:mod}`archivebox.workers.models`

```{py:module} archivebox.workers.models
```

```{autodoc2-docstring} archivebox.workers.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DefaultStatusChoices <archivebox.workers.models.DefaultStatusChoices>`
  -
* - {py:obj}`ModelWithQueue <archivebox.workers.models.ModelWithQueue>`
  - ```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`default_status_field <archivebox.workers.models.default_status_field>`
  - ```{autodoc2-docstring} archivebox.workers.models.default_status_field
    :summary:
    ```
* - {py:obj}`default_retry_at_field <archivebox.workers.models.default_retry_at_field>`
  - ```{autodoc2-docstring} archivebox.workers.models.default_retry_at_field
    :summary:
    ```
* - {py:obj}`RETRY_AT_MAX <archivebox.workers.models.RETRY_AT_MAX>`
  - ```{autodoc2-docstring} archivebox.workers.models.RETRY_AT_MAX
    :summary:
    ```
* - {py:obj}`ACTIVE_STATE_LEASE_SECONDS <archivebox.workers.models.ACTIVE_STATE_LEASE_SECONDS>`
  - ```{autodoc2-docstring} archivebox.workers.models.ACTIVE_STATE_LEASE_SECONDS
    :summary:
    ```
* - {py:obj}`logger <archivebox.workers.models.logger>`
  - ```{autodoc2-docstring} archivebox.workers.models.logger
    :summary:
    ```
* - {py:obj}`MODULE_PATH <archivebox.workers.models.MODULE_PATH>`
  - ```{autodoc2-docstring} archivebox.workers.models.MODULE_PATH
    :summary:
    ```
* - {py:obj}`REPO_ROOT <archivebox.workers.models.REPO_ROOT>`
  - ```{autodoc2-docstring} archivebox.workers.models.REPO_ROOT
    :summary:
    ```
* - {py:obj}`PACKAGE_ROOT <archivebox.workers.models.PACKAGE_ROOT>`
  - ```{autodoc2-docstring} archivebox.workers.models.PACKAGE_ROOT
    :summary:
    ```
````

### API

`````{py:class} DefaultStatusChoices()
:canonical: archivebox.workers.models.DefaultStatusChoices

Bases: {py:obj}`django.db.models.TextChoices`

````{py:attribute} QUEUED
:canonical: archivebox.workers.models.DefaultStatusChoices.QUEUED
:value: >
   ('queued', 'Queued')

```{autodoc2-docstring} archivebox.workers.models.DefaultStatusChoices.QUEUED
```

````

````{py:attribute} STARTED
:canonical: archivebox.workers.models.DefaultStatusChoices.STARTED
:value: >
   ('started', 'Started')

```{autodoc2-docstring} archivebox.workers.models.DefaultStatusChoices.STARTED
```

````

````{py:attribute} PAUSED
:canonical: archivebox.workers.models.DefaultStatusChoices.PAUSED
:value: >
   ('paused', 'Paused')

```{autodoc2-docstring} archivebox.workers.models.DefaultStatusChoices.PAUSED
```

````

````{py:attribute} SEALED
:canonical: archivebox.workers.models.DefaultStatusChoices.SEALED
:value: >
   ('sealed', 'Sealed')

```{autodoc2-docstring} archivebox.workers.models.DefaultStatusChoices.SEALED
```

````

`````

````{py:data} default_status_field
:canonical: archivebox.workers.models.default_status_field
:type: django.db.models.CharField
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.workers.models.default_status_field
```

````

````{py:data} default_retry_at_field
:canonical: archivebox.workers.models.default_retry_at_field
:type: django.db.models.DateTimeField
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.workers.models.default_retry_at_field
```

````

````{py:data} RETRY_AT_MAX
:canonical: archivebox.workers.models.RETRY_AT_MAX
:value: >
   'datetime(...)'

```{autodoc2-docstring} archivebox.workers.models.RETRY_AT_MAX
```

````

````{py:data} ACTIVE_STATE_LEASE_SECONDS
:canonical: archivebox.workers.models.ACTIVE_STATE_LEASE_SECONDS
:value: >
   60

```{autodoc2-docstring} archivebox.workers.models.ACTIVE_STATE_LEASE_SECONDS
```

````

````{py:data} logger
:canonical: archivebox.workers.models.logger
:value: >
   'getLogger(...)'

```{autodoc2-docstring} archivebox.workers.models.logger
```

````

````{py:data} MODULE_PATH
:canonical: archivebox.workers.models.MODULE_PATH
:value: >
   'resolve(...)'

```{autodoc2-docstring} archivebox.workers.models.MODULE_PATH
```

````

````{py:data} REPO_ROOT
:canonical: archivebox.workers.models.REPO_ROOT
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.REPO_ROOT
```

````

````{py:data} PACKAGE_ROOT
:canonical: archivebox.workers.models.PACKAGE_ROOT
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.PACKAGE_ROOT
```

````

``````{py:class} ModelWithQueue(*args, **kwargs)
:canonical: archivebox.workers.models.ModelWithQueue

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.__init__
```

````{py:attribute} StatusChoices
:canonical: archivebox.workers.models.ModelWithQueue.StatusChoices
:type: typing.ClassVar[type[django.db.models.TextChoices]]
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.StatusChoices
```

````

````{py:attribute} INITIAL_STATE
:canonical: archivebox.workers.models.ModelWithQueue.INITIAL_STATE
:type: typing.ClassVar[str]
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.INITIAL_STATE
```

````

````{py:attribute} ACTIVE_STATE
:canonical: archivebox.workers.models.ModelWithQueue.ACTIVE_STATE
:type: typing.ClassVar[str]
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.ACTIVE_STATE
```

````

````{py:attribute} FINAL_STATES
:canonical: archivebox.workers.models.ModelWithQueue.FINAL_STATES
:type: typing.ClassVar[tuple[str, ...]]
:value: >
   ()

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.FINAL_STATES
```

````

````{py:attribute} warn_on_save_outside_runner
:canonical: archivebox.workers.models.ModelWithQueue.warn_on_save_outside_runner
:type: typing.ClassVar[bool]
:value: >
   True

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.warn_on_save_outside_runner
```

````

````{py:attribute} status
:canonical: archivebox.workers.models.ModelWithQueue.status
:type: django.db.models.CharField
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.workers.models.ModelWithQueue.retry_at
:type: django.db.models.DateTimeField
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.retry_at
```

````

`````{py:class} Meta
:canonical: archivebox.workers.models.ModelWithQueue.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} app_label
:canonical: archivebox.workers.models.ModelWithQueue.Meta.app_label
:value: >
   'workers'

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.Meta.app_label
```

````

````{py:attribute} abstract
:canonical: archivebox.workers.models.ModelWithQueue.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.Meta.abstract
```

````

`````

````{py:attribute} FINAL_OR_ACTIVE_STATES
:canonical: archivebox.workers.models.ModelWithQueue.FINAL_OR_ACTIVE_STATES
:type: typing.ClassVar[tuple[str, ...]]
:value: >
   ()

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.FINAL_OR_ACTIVE_STATES
```

````

````{py:method} status_counts(queryset: django.db.models.QuerySet | None = None, statuses: collections.abc.Iterable[str] | None = None) -> dict[str, int]
:canonical: archivebox.workers.models.ModelWithQueue.status_counts
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.status_counts
```

````

````{py:property} RETRY_AT
:canonical: archivebox.workers.models.ModelWithQueue.RETRY_AT
:type: datetime.datetime | None

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.RETRY_AT
```

````

````{py:property} STATE
:canonical: archivebox.workers.models.ModelWithQueue.STATE
:type: str

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.STATE
```

````

````{py:method} bump_retry_at(seconds: int = 10) -> None
:canonical: archivebox.workers.models.ModelWithQueue.bump_retry_at

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.bump_retry_at
```

````

````{py:property} is_paused
:canonical: archivebox.workers.models.ModelWithQueue.is_paused
:type: bool

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.is_paused
```

````

````{py:method} safe_update(update_fields: dict[str, typing.Any], *, refresh: bool = True, extra_filter: dict[str, typing.Any] | None = None) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.safe_update

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.safe_update
```

````

````{py:method} save(*args: typing.Any, **kwargs: typing.Any) -> None
:canonical: archivebox.workers.models.ModelWithQueue.save

````

````{py:method} pause(*, save: bool = True) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.pause

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.pause
```

````

````{py:method} resume(*, when: datetime.datetime | None = None, save: bool = True) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.resume

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.resume
```

````

````{py:method} update_and_requeue(*, refresh: bool = True, **kwargs: typing.Any) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.update_and_requeue

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.update_and_requeue
```

````

````{py:method} get_queue()
:canonical: archivebox.workers.models.ModelWithQueue.get_queue
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.get_queue
```

````

````{py:method} claim_for_worker(obj: archivebox.workers.models.ModelWithQueue, lock_seconds: int = 60) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.claim_for_worker
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.claim_for_worker
```

````

````{py:method} claim_processing_lock(lock_seconds: int = 60) -> bool
:canonical: archivebox.workers.models.ModelWithQueue.claim_processing_lock

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.claim_processing_lock
```

````

````{py:method} extend_choices(base_choices: type[django.db.models.TextChoices])
:canonical: archivebox.workers.models.ModelWithQueue.extend_choices
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.extend_choices
```

````

````{py:method} StatusField(**kwargs: typing.Any) -> django.db.models.CharField
:canonical: archivebox.workers.models.ModelWithQueue.StatusField
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.StatusField
```

````

````{py:method} RetryAtField(**kwargs: typing.Any) -> django.db.models.DateTimeField
:canonical: archivebox.workers.models.ModelWithQueue.RetryAtField
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.ModelWithQueue.RetryAtField
```

````

``````
