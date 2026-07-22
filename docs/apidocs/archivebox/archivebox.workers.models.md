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
* - {py:obj}`ModelStateMachine <archivebox.workers.models.ModelStateMachine>`
  -
* - {py:obj}`BaseModelWithStateMachine <archivebox.workers.models.BaseModelWithStateMachine>`
  -
* - {py:obj}`ModelWithStateMachine <archivebox.workers.models.ModelWithStateMachine>`
  -
* - {py:obj}`BaseStateMachine <archivebox.workers.models.BaseStateMachine>`
  - ```{autodoc2-docstring} archivebox.workers.models.BaseStateMachine
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
* - {py:obj}`ObjectState <archivebox.workers.models.ObjectState>`
  - ```{autodoc2-docstring} archivebox.workers.models.ObjectState
    :summary:
    ```
* - {py:obj}`ObjectStateList <archivebox.workers.models.ObjectStateList>`
  - ```{autodoc2-docstring} archivebox.workers.models.ObjectStateList
    :summary:
    ```
````

### API

`````{py:class} DefaultStatusChoices(*args, **kwds)
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

````{py:data} ObjectState
:canonical: archivebox.workers.models.ObjectState
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ObjectState
```

````

````{py:data} ObjectStateList
:canonical: archivebox.workers.models.ObjectStateList
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ObjectStateList
```

````

`````{py:class} ModelStateMachine
:canonical: archivebox.workers.models.ModelStateMachine

Bases: {py:obj}`typing.Protocol`

````{py:method} tick() -> typing.Any
:canonical: archivebox.workers.models.ModelStateMachine.tick

```{autodoc2-docstring} archivebox.workers.models.ModelStateMachine.tick
```

````

````{py:method} pause_requested() -> typing.Any
:canonical: archivebox.workers.models.ModelStateMachine.pause_requested

```{autodoc2-docstring} archivebox.workers.models.ModelStateMachine.pause_requested
```

````

````{py:method} resume_requested() -> typing.Any
:canonical: archivebox.workers.models.ModelStateMachine.resume_requested

```{autodoc2-docstring} archivebox.workers.models.ModelStateMachine.resume_requested
```

````

`````

``````{py:class} BaseModelWithStateMachine(*args, **kwargs)
:canonical: archivebox.workers.models.BaseModelWithStateMachine

Bases: {py:obj}`django.db.models.Model`

````{py:attribute} StatusChoices
:canonical: archivebox.workers.models.BaseModelWithStateMachine.StatusChoices
:type: typing.ClassVar[type[archivebox.workers.models.DefaultStatusChoices]]
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.StatusChoices
```

````

````{py:attribute} state_machine_name
:canonical: archivebox.workers.models.BaseModelWithStateMachine.state_machine_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.state_machine_name
```

````

````{py:attribute} state_field_name
:canonical: archivebox.workers.models.BaseModelWithStateMachine.state_field_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.state_field_name
```

````

````{py:attribute} state_machine_attr
:canonical: archivebox.workers.models.BaseModelWithStateMachine.state_machine_attr
:type: str
:value: >
   'sm'

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.state_machine_attr
```

````

````{py:attribute} bind_events_as_methods
:canonical: archivebox.workers.models.BaseModelWithStateMachine.bind_events_as_methods
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.bind_events_as_methods
```

````

````{py:attribute} warn_on_save_outside_runner
:canonical: archivebox.workers.models.BaseModelWithStateMachine.warn_on_save_outside_runner
:type: typing.ClassVar[bool]
:value: >
   True

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.warn_on_save_outside_runner
```

````

````{py:attribute} active_state
:canonical: archivebox.workers.models.BaseModelWithStateMachine.active_state
:type: archivebox.workers.models.ObjectState
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.active_state
```

````

````{py:attribute} retry_at_field_name
:canonical: archivebox.workers.models.BaseModelWithStateMachine.retry_at_field_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.retry_at_field_name
```

````

`````{py:class} Meta
:canonical: archivebox.workers.models.BaseModelWithStateMachine.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} app_label
:canonical: archivebox.workers.models.BaseModelWithStateMachine.Meta.app_label
:value: >
   'workers'

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.Meta.app_label
```

````

````{py:attribute} abstract
:canonical: archivebox.workers.models.BaseModelWithStateMachine.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.Meta.abstract
```

````

`````

````{py:property} sm
:canonical: archivebox.workers.models.BaseModelWithStateMachine.sm
:type: statemachine.StateMachine

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.sm
```

````

````{py:method} status_counts(queryset: django.db.models.QuerySet | None = None, statuses: collections.abc.Iterable[str] | None = None) -> dict[str, int]
:canonical: archivebox.workers.models.BaseModelWithStateMachine.status_counts
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.status_counts
```

````

````{py:method} check(sender=None, **kwargs)
:canonical: archivebox.workers.models.BaseModelWithStateMachine.check
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.check
```

````

````{py:method} _state_to_str(state: archivebox.workers.models.ObjectState) -> str
:canonical: archivebox.workers.models.BaseModelWithStateMachine._state_to_str
:staticmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine._state_to_str
```

````

````{py:property} RETRY_AT
:canonical: archivebox.workers.models.BaseModelWithStateMachine.RETRY_AT
:type: datetime.datetime

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.RETRY_AT
```

````

````{py:property} STATE
:canonical: archivebox.workers.models.BaseModelWithStateMachine.STATE
:type: str

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.STATE
```

````

````{py:method} bump_retry_at(seconds: int = 10)
:canonical: archivebox.workers.models.BaseModelWithStateMachine.bump_retry_at

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.bump_retry_at
```

````

````{py:property} is_paused
:canonical: archivebox.workers.models.BaseModelWithStateMachine.is_paused
:type: bool

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.is_paused
```

````

````{py:method} safe_update(update_fields: dict[str, typing.Any], *, refresh: bool = True, extra_filter: dict[str, typing.Any] | None = None) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.safe_update

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.safe_update
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.workers.models.BaseModelWithStateMachine.save

````

````{py:method} pause(*, save: bool = True) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.pause

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.pause
```

````

````{py:method} resume(*, when: datetime.datetime | None = None, save: bool = True) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.resume

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.resume
```

````

````{py:method} update_and_requeue(*, refresh: bool = True, **kwargs) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.update_and_requeue

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.update_and_requeue
```

````

````{py:method} get_queue()
:canonical: archivebox.workers.models.BaseModelWithStateMachine.get_queue
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.get_queue
```

````

````{py:method} claim_for_worker(obj: archivebox.workers.models.BaseModelWithStateMachine, lock_seconds: int = 60) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.claim_for_worker
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.claim_for_worker
```

````

````{py:method} claim_processing_lock(lock_seconds: int = 60) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.claim_processing_lock

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.claim_processing_lock
```

````

````{py:method} tick_claimed(lock_seconds: int = 60) -> bool
:canonical: archivebox.workers.models.BaseModelWithStateMachine.tick_claimed

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.tick_claimed
```

````

````{py:method} ACTIVE_STATE() -> str
:canonical: archivebox.workers.models.BaseModelWithStateMachine.ACTIVE_STATE

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.ACTIVE_STATE
```

````

````{py:method} INITIAL_STATE() -> str
:canonical: archivebox.workers.models.BaseModelWithStateMachine.INITIAL_STATE

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.INITIAL_STATE
```

````

````{py:method} FINAL_STATES() -> list[str]
:canonical: archivebox.workers.models.BaseModelWithStateMachine.FINAL_STATES

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.FINAL_STATES
```

````

````{py:method} FINAL_OR_ACTIVE_STATES() -> list[str]
:canonical: archivebox.workers.models.BaseModelWithStateMachine.FINAL_OR_ACTIVE_STATES

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.FINAL_OR_ACTIVE_STATES
```

````

````{py:method} extend_choices(base_choices: type[django.db.models.TextChoices])
:canonical: archivebox.workers.models.BaseModelWithStateMachine.extend_choices
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.extend_choices
```

````

````{py:method} StatusField(**kwargs) -> django.db.models.CharField
:canonical: archivebox.workers.models.BaseModelWithStateMachine.StatusField
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.StatusField
```

````

````{py:method} RetryAtField(**kwargs) -> django.db.models.DateTimeField
:canonical: archivebox.workers.models.BaseModelWithStateMachine.RetryAtField
:classmethod:

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.RetryAtField
```

````

````{py:method} StateMachineClass() -> type[statemachine.StateMachine]
:canonical: archivebox.workers.models.BaseModelWithStateMachine.StateMachineClass

```{autodoc2-docstring} archivebox.workers.models.BaseModelWithStateMachine.StateMachineClass
```

````

``````

``````{py:class} ModelWithStateMachine(*args, **kwargs)
:canonical: archivebox.workers.models.ModelWithStateMachine

Bases: {py:obj}`archivebox.workers.models.BaseModelWithStateMachine`

````{py:attribute} StatusChoices
:canonical: archivebox.workers.models.ModelWithStateMachine.StatusChoices
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.StatusChoices
```

````

````{py:attribute} status
:canonical: archivebox.workers.models.ModelWithStateMachine.status
:type: django.db.models.CharField
:value: >
   'StatusField(...)'

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.workers.models.ModelWithStateMachine.retry_at
:type: django.db.models.DateTimeField
:value: >
   'RetryAtField(...)'

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.retry_at
```

````

````{py:attribute} state_machine_name
:canonical: archivebox.workers.models.ModelWithStateMachine.state_machine_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.state_machine_name
```

````

````{py:attribute} state_field_name
:canonical: archivebox.workers.models.ModelWithStateMachine.state_field_name
:type: str
:value: >
   'status'

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.state_field_name
```

````

````{py:attribute} state_machine_attr
:canonical: archivebox.workers.models.ModelWithStateMachine.state_machine_attr
:type: str
:value: >
   'sm'

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.state_machine_attr
```

````

````{py:attribute} bind_events_as_methods
:canonical: archivebox.workers.models.ModelWithStateMachine.bind_events_as_methods
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.bind_events_as_methods
```

````

````{py:attribute} active_state
:canonical: archivebox.workers.models.ModelWithStateMachine.active_state
:value: >
   None

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.active_state
```

````

````{py:attribute} retry_at_field_name
:canonical: archivebox.workers.models.ModelWithStateMachine.retry_at_field_name
:type: str
:value: >
   'retry_at'

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.retry_at_field_name
```

````

`````{py:class} Meta
:canonical: archivebox.workers.models.ModelWithStateMachine.Meta

Bases: {py:obj}`archivebox.workers.models.BaseModelWithStateMachine`

````{py:attribute} abstract
:canonical: archivebox.workers.models.ModelWithStateMachine.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.workers.models.ModelWithStateMachine.Meta.abstract
```

````

`````

``````

`````{py:class} BaseStateMachine(obj, *args, **kwargs)
:canonical: archivebox.workers.models.BaseStateMachine

Bases: {py:obj}`statemachine.StateMachine`

```{autodoc2-docstring} archivebox.workers.models.BaseStateMachine
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.workers.models.BaseStateMachine.__init__
```

````{py:attribute} model_attr_name
:canonical: archivebox.workers.models.BaseStateMachine.model_attr_name
:type: str
:value: >
   'obj'

```{autodoc2-docstring} archivebox.workers.models.BaseStateMachine.model_attr_name
```

````

````{py:method} _register_callbacks(listeners: list[object])
:canonical: archivebox.workers.models.BaseStateMachine._register_callbacks

```{autodoc2-docstring} archivebox.workers.models.BaseStateMachine._register_callbacks
```

````

````{py:method} __repr__() -> str
:canonical: archivebox.workers.models.BaseStateMachine.__repr__

````

````{py:method} __str__() -> str
:canonical: archivebox.workers.models.BaseStateMachine.__str__

````

`````
