# {py:mod}`archivebox.base_models.models`

```{py:module} archivebox.base_models.models
```

```{autodoc2-docstring} archivebox.base_models.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AutoDateTimeField <archivebox.base_models.models.AutoDateTimeField>`
  - ```{autodoc2-docstring} archivebox.base_models.models.AutoDateTimeField
    :summary:
    ```
* - {py:obj}`ModelWithUUID <archivebox.base_models.models.ModelWithUUID>`
  -
* - {py:obj}`ModelWithNotes <archivebox.base_models.models.ModelWithNotes>`
  - ```{autodoc2-docstring} archivebox.base_models.models.ModelWithNotes
    :summary:
    ```
* - {py:obj}`ModelWithHealthStats <archivebox.base_models.models.ModelWithHealthStats>`
  - ```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats
    :summary:
    ```
* - {py:obj}`ModelWithConfig <archivebox.base_models.models.ModelWithConfig>`
  - ```{autodoc2-docstring} archivebox.base_models.models.ModelWithConfig
    :summary:
    ```
* - {py:obj}`ModelWithDeleteAfter <archivebox.base_models.models.ModelWithDeleteAfter>`
  -
* - {py:obj}`ModelWithOutputDir <archivebox.base_models.models.ModelWithOutputDir>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`normalize_config_json_values <archivebox.base_models.models.normalize_config_json_values>`
  - ```{autodoc2-docstring} archivebox.base_models.models.normalize_config_json_values
    :summary:
    ```
* - {py:obj}`get_or_create_system_user_pk <archivebox.base_models.models.get_or_create_system_user_pk>`
  - ```{autodoc2-docstring} archivebox.base_models.models.get_or_create_system_user_pk
    :summary:
    ```
````

### API

````{py:function} normalize_config_json_values(config: typing.Any) -> typing.Any
:canonical: archivebox.base_models.models.normalize_config_json_values

```{autodoc2-docstring} archivebox.base_models.models.normalize_config_json_values
```
````

````{py:function} get_or_create_system_user_pk(username='system')
:canonical: archivebox.base_models.models.get_or_create_system_user_pk

```{autodoc2-docstring} archivebox.base_models.models.get_or_create_system_user_pk
```
````

`````{py:class} AutoDateTimeField(verbose_name=None, name=None, auto_now=False, auto_now_add=False, **kwargs)
:canonical: archivebox.base_models.models.AutoDateTimeField

Bases: {py:obj}`django.db.models.DateTimeField`

```{autodoc2-docstring} archivebox.base_models.models.AutoDateTimeField
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.base_models.models.AutoDateTimeField.__init__
```

````{py:method} pre_save(model_instance, add)
:canonical: archivebox.base_models.models.AutoDateTimeField.pre_save

````

`````

``````{py:class} ModelWithUUID(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithUUID

Bases: {py:obj}`django.db.models.Model`

````{py:attribute} id
:canonical: archivebox.base_models.models.ModelWithUUID.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.id
```

````

````{py:attribute} created_at
:canonical: archivebox.base_models.models.ModelWithUUID.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.base_models.models.ModelWithUUID.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.modified_at
```

````

````{py:attribute} created_by
:canonical: archivebox.base_models.models.ModelWithUUID.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.created_by
```

````

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithUUID.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithUUID.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.Meta.abstract
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.base_models.models.ModelWithUUID.__str__

````

````{py:property} admin_change_url
:canonical: archivebox.base_models.models.ModelWithUUID.admin_change_url
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.admin_change_url
```

````

````{py:property} api_url
:canonical: archivebox.base_models.models.ModelWithUUID.api_url
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.api_url
```

````

````{py:property} api_docs_url
:canonical: archivebox.base_models.models.ModelWithUUID.api_docs_url
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithUUID.api_docs_url
```

````

``````

``````{py:class} ModelWithNotes(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithNotes

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.base_models.models.ModelWithNotes
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.base_models.models.ModelWithNotes.__init__
```

````{py:attribute} notes
:canonical: archivebox.base_models.models.ModelWithNotes.notes
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithNotes.notes
```

````

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithNotes.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithNotes.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithNotes.Meta.abstract
```

````

`````

``````

``````{py:class} ModelWithHealthStats(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithHealthStats

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.__init__
```

````{py:attribute} num_uses_failed
:canonical: archivebox.base_models.models.ModelWithHealthStats.num_uses_failed
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.num_uses_failed
```

````

````{py:attribute} num_uses_succeeded
:canonical: archivebox.base_models.models.ModelWithHealthStats.num_uses_succeeded
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.num_uses_succeeded
```

````

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithHealthStats.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithHealthStats.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.Meta.abstract
```

````

`````

````{py:property} admin_change_url
:canonical: archivebox.base_models.models.ModelWithHealthStats.admin_change_url
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.admin_change_url
```

````

````{py:property} health
:canonical: archivebox.base_models.models.ModelWithHealthStats.health
:type: int

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.health
```

````

````{py:method} increment_health_stats(success: bool)
:canonical: archivebox.base_models.models.ModelWithHealthStats.increment_health_stats

```{autodoc2-docstring} archivebox.base_models.models.ModelWithHealthStats.increment_health_stats
```

````

``````

``````{py:class} ModelWithConfig(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithConfig

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.base_models.models.ModelWithConfig
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.base_models.models.ModelWithConfig.__init__
```

````{py:attribute} config
:canonical: archivebox.base_models.models.ModelWithConfig.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithConfig.config
```

````

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithConfig.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithConfig.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithConfig.Meta.abstract
```

````

`````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithConfig.save

````

``````

``````{py:class} ModelWithDeleteAfter(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithDeleteAfter

Bases: {py:obj}`django.db.models.Model`

````{py:attribute} delete_after_final_statuses
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.delete_after_final_statuses
:type: tuple[str, ...]
:value: >
   ()

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.delete_after_final_statuses
```

````

````{py:attribute} delete_at
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.delete_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.delete_at
```

````

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.Meta.abstract
```

````

`````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.save

````

````{py:method} get_delete_after_config_value()
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.get_delete_after_config_value

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.get_delete_after_config_value
```

````

````{py:method} set_delete_at_from_config(config_value=None) -> bool
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.set_delete_at_from_config

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.set_delete_at_from_config
```

````

````{py:method} missing_delete_at_candidates()
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.missing_delete_at_candidates
:classmethod:

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.missing_delete_at_candidates
```

````

````{py:method} delete_expired(*, batch_size: int = 100, backfill_missing: bool = True) -> int
:canonical: archivebox.base_models.models.ModelWithDeleteAfter.delete_expired
:classmethod:

```{autodoc2-docstring} archivebox.base_models.models.ModelWithDeleteAfter.delete_expired
```

````

``````

``````{py:class} ModelWithOutputDir(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithOutputDir

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID`

`````{py:class} Meta
:canonical: archivebox.base_models.models.ModelWithOutputDir.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID`

````{py:attribute} abstract
:canonical: archivebox.base_models.models.ModelWithOutputDir.Meta.abstract
:value: >
   True

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.Meta.abstract
```

````

`````

````{py:attribute} _delete_signal_registered
:canonical: archivebox.base_models.models.ModelWithOutputDir._delete_signal_registered
:value: >
   False

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir._delete_signal_registered
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.base_models.models.ModelWithOutputDir.save

````

````{py:property} output_dir_parent
:canonical: archivebox.base_models.models.ModelWithOutputDir.output_dir_parent
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.output_dir_parent
```

````

````{py:property} output_dir_name
:canonical: archivebox.base_models.models.ModelWithOutputDir.output_dir_name
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.output_dir_name
```

````

````{py:property} output_dir_str
:canonical: archivebox.base_models.models.ModelWithOutputDir.output_dir_str
:type: str

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.output_dir_str
```

````

````{py:property} output_dir
:canonical: archivebox.base_models.models.ModelWithOutputDir.output_dir
:abstractmethod:
:type: pathlib.Path

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.output_dir
```

````

````{py:method} output_paths_for_delete() -> tuple[pathlib.Path, ...]
:canonical: archivebox.base_models.models.ModelWithOutputDir.output_paths_for_delete

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.output_paths_for_delete
```

````

````{py:method} validate_output_paths_for_delete(paths) -> tuple[pathlib.Path, ...]
:canonical: archivebox.base_models.models.ModelWithOutputDir.validate_output_paths_for_delete
:classmethod:

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.validate_output_paths_for_delete
```

````

````{py:method} delete_output_paths(paths) -> None
:canonical: archivebox.base_models.models.ModelWithOutputDir.delete_output_paths
:classmethod:

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.delete_output_paths
```

````

````{py:method} register_delete_signal() -> None
:canonical: archivebox.base_models.models.ModelWithOutputDir.register_delete_signal
:classmethod:

```{autodoc2-docstring} archivebox.base_models.models.ModelWithOutputDir.register_delete_signal
```

````

``````
