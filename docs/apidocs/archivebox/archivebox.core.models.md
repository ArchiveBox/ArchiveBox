# {py:mod}`archivebox.core.models`

```{py:module} archivebox.core.models
```

```{autodoc2-docstring} archivebox.core.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`UngroupedSubquery <archivebox.core.models.UngroupedSubquery>`
  - ```{autodoc2-docstring} archivebox.core.models.UngroupedSubquery
    :summary:
    ```
* - {py:obj}`Tag <archivebox.core.models.Tag>`
  -
* - {py:obj}`SnapshotTag <archivebox.core.models.SnapshotTag>`
  -
* - {py:obj}`SnapshotQuerySet <archivebox.core.models.SnapshotQuerySet>`
  - ```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet
    :summary:
    ```
* - {py:obj}`SnapshotManager <archivebox.core.models.SnapshotManager>`
  - ```{autodoc2-docstring} archivebox.core.models.SnapshotManager
    :summary:
    ```
* - {py:obj}`Snapshot <archivebox.core.models.Snapshot>`
  -
* - {py:obj}`ArchiveResult <archivebox.core.models.ArchiveResult>`
  -
````

### API

````{py:exception} SnapshotMigrationError()
:canonical: archivebox.core.models.SnapshotMigrationError

Bases: {py:obj}`RuntimeError`

```{autodoc2-docstring} archivebox.core.models.SnapshotMigrationError
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.models.SnapshotMigrationError.__init__
```

````

`````{py:class} UngroupedSubquery(queryset, output_field=None, **extra)
:canonical: archivebox.core.models.UngroupedSubquery

Bases: {py:obj}`django.db.models.Subquery`

```{autodoc2-docstring} archivebox.core.models.UngroupedSubquery
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.models.UngroupedSubquery.__init__
```

````{py:method} get_group_by_cols()
:canonical: archivebox.core.models.UngroupedSubquery.get_group_by_cols

```{autodoc2-docstring} archivebox.core.models.UngroupedSubquery.get_group_by_cols
```

````

`````

``````{py:class} Tag(*args, **kwargs)
:canonical: archivebox.core.models.Tag

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID`

````{py:attribute} id
:canonical: archivebox.core.models.Tag.id
:value: >
   'AutoField(...)'

```{autodoc2-docstring} archivebox.core.models.Tag.id
```

````

````{py:attribute} created_by
:canonical: archivebox.core.models.Tag.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.Tag.created_by
```

````

````{py:attribute} created_at
:canonical: archivebox.core.models.Tag.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Tag.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.core.models.Tag.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Tag.modified_at
```

````

````{py:attribute} name
:canonical: archivebox.core.models.Tag.name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.Tag.name
```

````

````{py:attribute} snapshot_set
:canonical: archivebox.core.models.Tag.snapshot_set
:type: django.db.models.Manager[Snapshot]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Tag.snapshot_set
```

````

`````{py:class} Meta
:canonical: archivebox.core.models.Tag.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID.Meta`

````{py:attribute} app_label
:canonical: archivebox.core.models.Tag.Meta.app_label
:value: >
   'core'

```{autodoc2-docstring} archivebox.core.models.Tag.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.core.models.Tag.Meta.verbose_name
:value: >
   'Tag'

```{autodoc2-docstring} archivebox.core.models.Tag.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.core.models.Tag.Meta.verbose_name_plural
:value: >
   'Tags'

```{autodoc2-docstring} archivebox.core.models.Tag.Meta.verbose_name_plural
```

````

`````

````{py:method} __str__()
:canonical: archivebox.core.models.Tag.__str__

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.core.models.Tag.save

````

````{py:property} slug
:canonical: archivebox.core.models.Tag.slug
:type: str

```{autodoc2-docstring} archivebox.core.models.Tag.slug
```

````

````{py:property} api_url
:canonical: archivebox.core.models.Tag.api_url
:type: str

```{autodoc2-docstring} archivebox.core.models.Tag.api_url
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.core.models.Tag.to_json

```{autodoc2-docstring} archivebox.core.models.Tag.to_json
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None)
:canonical: archivebox.core.models.Tag.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Tag.from_json
```

````

``````

``````{py:class} SnapshotTag(*args, **kwargs)
:canonical: archivebox.core.models.SnapshotTag

Bases: {py:obj}`django.db.models.Model`

````{py:attribute} id
:canonical: archivebox.core.models.SnapshotTag.id
:value: >
   'AutoField(...)'

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.id
```

````

````{py:attribute} snapshot
:canonical: archivebox.core.models.SnapshotTag.snapshot
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.snapshot
```

````

````{py:attribute} tag
:canonical: archivebox.core.models.SnapshotTag.tag
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.tag
```

````

`````{py:class} Meta
:canonical: archivebox.core.models.SnapshotTag.Meta

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.Meta
```

````{py:attribute} app_label
:canonical: archivebox.core.models.SnapshotTag.Meta.app_label
:value: >
   'core'

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.Meta.app_label
```

````

````{py:attribute} db_table
:canonical: archivebox.core.models.SnapshotTag.Meta.db_table
:value: >
   'core_snapshot_tags'

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.Meta.db_table
```

````

````{py:attribute} unique_together
:canonical: archivebox.core.models.SnapshotTag.Meta.unique_together
:type: typing.ClassVar[list[tuple[str, str]]]
:value: >
   [('snapshot', 'tag')]

```{autodoc2-docstring} archivebox.core.models.SnapshotTag.Meta.unique_together
```

````

`````

``````

`````{py:class} SnapshotQuerySet(model=None, query=None, using=None, hints=None)
:canonical: archivebox.core.models.SnapshotQuerySet

Bases: {py:obj}`django.db.models.QuerySet`

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.__init__
```

````{py:method} bulk_create(objs, *args, **kwargs)
:canonical: archivebox.core.models.SnapshotQuerySet.bulk_create

````

````{py:method} paged_iterator(chunk_size: int = 500)
:canonical: archivebox.core.models.SnapshotQuerySet.paged_iterator

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.paged_iterator
```

````

````{py:attribute} FILTER_TYPES
:canonical: archivebox.core.models.SnapshotQuerySet.FILTER_TYPES
:type: typing.ClassVar[dict[str, typing.Any]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.FILTER_TYPES
```

````

````{py:attribute} FILTER_TYPE_CHOICES
:canonical: archivebox.core.models.SnapshotQuerySet.FILTER_TYPE_CHOICES
:value: >
   'tuple(...)'

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.FILTER_TYPE_CHOICES
```

````

````{py:attribute} FILTER_ARG_KEYS
:canonical: archivebox.core.models.SnapshotQuerySet.FILTER_ARG_KEYS
:value: >
   ('after', 'before', 'filter_type', 'filter_patterns', 'status', 'url__icontains', 'url__istartswith'...

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.FILTER_ARG_KEYS
```

````

````{py:attribute} SPECIAL_FILTER_ARG_KEYS
:canonical: archivebox.core.models.SnapshotQuerySet.SPECIAL_FILTER_ARG_KEYS
:value: >
   'frozenset(...)'

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.SPECIAL_FILTER_ARG_KEYS
```

````

````{py:method} filter_by_patterns(patterns: list[str], filter_type: str = 'exact') -> archivebox.core.models.SnapshotQuerySet
:canonical: archivebox.core.models.SnapshotQuerySet.filter_by_patterns

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.filter_by_patterns
```

````

````{py:method} search(**kwargs) -> archivebox.core.models.SnapshotQuerySet
:canonical: archivebox.core.models.SnapshotQuerySet.search

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.search
```

````

````{py:method} to_json(with_headers: bool = False) -> str
:canonical: archivebox.core.models.SnapshotQuerySet.to_json

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.to_json
```

````

````{py:method} to_csv(cols: list[str] | None = None, header: bool = True, separator: str = ',', ljust: int = 0) -> str
:canonical: archivebox.core.models.SnapshotQuerySet.to_csv

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.to_csv
```

````

````{py:method} to_html(with_headers: bool = True) -> str
:canonical: archivebox.core.models.SnapshotQuerySet.to_html

```{autodoc2-docstring} archivebox.core.models.SnapshotQuerySet.to_html
```

````

`````

`````{py:class} SnapshotManager
:canonical: archivebox.core.models.SnapshotManager

Bases: {py:obj}`models.Manager.from_queryset`\({py:obj}`SnapshotQuerySet`\)

```{autodoc2-docstring} archivebox.core.models.SnapshotManager
```

````{py:method} filter(*args, **kwargs)
:canonical: archivebox.core.models.SnapshotManager.filter

```{autodoc2-docstring} archivebox.core.models.SnapshotManager.filter
```

````

````{py:method} get_queryset()
:canonical: archivebox.core.models.SnapshotManager.get_queryset

```{autodoc2-docstring} archivebox.core.models.SnapshotManager.get_queryset
```

````

````{py:method} remove(atomic: bool = False) -> tuple
:canonical: archivebox.core.models.SnapshotManager.remove

```{autodoc2-docstring} archivebox.core.models.SnapshotManager.remove
```

````

`````

``````{py:class} Snapshot(*args, **kwargs)
:canonical: archivebox.core.models.Snapshot

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir`, {py:obj}`archivebox.base_models.models.ModelWithConfig`, {py:obj}`archivebox.base_models.models.ModelWithNotes`, {py:obj}`archivebox.base_models.models.ModelWithHealthStats`, {py:obj}`archivebox.workers.models.ModelWithQueue`

````{py:attribute} BROWSER_EXTENSION_UPLOAD_HOOK_NAME
:canonical: archivebox.core.models.Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME
:value: >
   'on_Snapshot__archivebox_browser_extension_upload'

```{autodoc2-docstring} archivebox.core.models.Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME
```

````

````{py:attribute} INTERNAL_INPUT_URL
:canonical: archivebox.core.models.Snapshot.INTERNAL_INPUT_URL
:value: >
   'archivebox://internal'

```{autodoc2-docstring} archivebox.core.models.Snapshot.INTERNAL_INPUT_URL
```

````

````{py:attribute} id
:canonical: archivebox.core.models.Snapshot.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.id
```

````

````{py:attribute} created_at
:canonical: archivebox.core.models.Snapshot.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.core.models.Snapshot.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.modified_at
```

````

````{py:attribute} url
:canonical: archivebox.core.models.Snapshot.url
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.url
```

````

````{py:attribute} timestamp
:canonical: archivebox.core.models.Snapshot.timestamp
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.timestamp
```

````

````{py:attribute} bookmarked_at
:canonical: archivebox.core.models.Snapshot.bookmarked_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.bookmarked_at
```

````

````{py:attribute} crawl
:canonical: archivebox.core.models.Snapshot.crawl
:type: archivebox.crawls.models.Crawl
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.crawl
```

````

````{py:attribute} parent_snapshot
:canonical: archivebox.core.models.Snapshot.parent_snapshot
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.parent_snapshot
```

````

````{py:attribute} title
:canonical: archivebox.core.models.Snapshot.title
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.title
```

````

````{py:attribute} downloaded_at
:canonical: archivebox.core.models.Snapshot.downloaded_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.downloaded_at
```

````

````{py:attribute} depth
:canonical: archivebox.core.models.Snapshot.depth
:value: >
   'PositiveSmallIntegerField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.depth
```

````

````{py:attribute} fs_version
:canonical: archivebox.core.models.Snapshot.fs_version
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.fs_version
```

````

````{py:attribute} current_step
:canonical: archivebox.core.models.Snapshot.current_step
:value: >
   'PositiveSmallIntegerField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.current_step
```

````

````{py:attribute} retry_at
:canonical: archivebox.core.models.Snapshot.retry_at
:value: >
   'RetryAtField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.retry_at
```

````

````{py:attribute} status
:canonical: archivebox.core.models.Snapshot.status
:value: >
   'StatusField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.status
```

````

````{py:attribute} config
:canonical: archivebox.core.models.Snapshot.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.config
```

````

````{py:attribute} permissions
:canonical: archivebox.core.models.Snapshot.permissions
:value: >
   'GeneratedField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.permissions
```

````

````{py:attribute} output_size
:canonical: archivebox.core.models.Snapshot.output_size
:value: >
   'BigIntegerField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.output_size
```

````

````{py:attribute} notes
:canonical: archivebox.core.models.Snapshot.notes
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.notes
```

````

````{py:attribute} tags
:canonical: archivebox.core.models.Snapshot.tags
:value: >
   'ManyToManyField(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.tags
```

````

````{py:attribute} state_field_name
:canonical: archivebox.core.models.Snapshot.state_field_name
:value: >
   'status'

```{autodoc2-docstring} archivebox.core.models.Snapshot.state_field_name
```

````

````{py:attribute} retry_at_field_name
:canonical: archivebox.core.models.Snapshot.retry_at_field_name
:value: >
   'retry_at'

```{autodoc2-docstring} archivebox.core.models.Snapshot.retry_at_field_name
```

````

````{py:attribute} StatusChoices
:canonical: archivebox.core.models.Snapshot.StatusChoices
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.StatusChoices
```

````

````{py:attribute} INITIAL_STATE
:canonical: archivebox.core.models.Snapshot.INITIAL_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.INITIAL_STATE
```

````

````{py:attribute} ACTIVE_STATE
:canonical: archivebox.core.models.Snapshot.ACTIVE_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.ACTIVE_STATE
```

````

````{py:attribute} FINAL_STATES
:canonical: archivebox.core.models.Snapshot.FINAL_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.Snapshot.FINAL_STATES
```

````

````{py:attribute} FINAL_OR_ACTIVE_STATES
:canonical: archivebox.core.models.Snapshot.FINAL_OR_ACTIVE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.Snapshot.FINAL_OR_ACTIVE_STATES
```

````

````{py:attribute} active_state
:canonical: archivebox.core.models.Snapshot.active_state
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.active_state
```

````

````{py:attribute} delete_after_final_statuses
:canonical: archivebox.core.models.Snapshot.delete_after_final_statuses
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.Snapshot.delete_after_final_statuses
```

````

````{py:attribute} RUNNABLE_STATES
:canonical: archivebox.core.models.Snapshot.RUNNABLE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.Snapshot.RUNNABLE_STATES
```

````

````{py:attribute} OPEN_STATES
:canonical: archivebox.core.models.Snapshot.OPEN_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.Snapshot.OPEN_STATES
```

````

````{py:attribute} crawl_id
:canonical: archivebox.core.models.Snapshot.crawl_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.crawl_id
```

````

````{py:attribute} parent_snapshot_id
:canonical: archivebox.core.models.Snapshot.parent_snapshot_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.parent_snapshot_id
```

````

````{py:attribute} _prefetched_objects_cache
:canonical: archivebox.core.models.Snapshot._prefetched_objects_cache
:type: dict[str, typing.Any]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot._prefetched_objects_cache
```

````

````{py:attribute} objects
:canonical: archivebox.core.models.Snapshot.objects
:value: >
   'SnapshotManager(...)'

```{autodoc2-docstring} archivebox.core.models.Snapshot.objects
```

````

````{py:attribute} archiveresult_set
:canonical: archivebox.core.models.Snapshot.archiveresult_set
:type: django.db.models.Manager[ArchiveResult]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.archiveresult_set
```

````

````{py:method} add_tag_ids(tag_ids: collections.abc.Iterable[int | str]) -> None
:canonical: archivebox.core.models.Snapshot.add_tag_ids

```{autodoc2-docstring} archivebox.core.models.Snapshot.add_tag_ids
```

````

`````{py:class} Meta
:canonical: archivebox.core.models.Snapshot.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter.Meta`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir.Meta`, {py:obj}`archivebox.base_models.models.ModelWithConfig.Meta`, {py:obj}`archivebox.base_models.models.ModelWithNotes.Meta`, {py:obj}`archivebox.base_models.models.ModelWithHealthStats.Meta`, {py:obj}`archivebox.workers.models.ModelWithQueue.Meta`

````{py:attribute} app_label
:canonical: archivebox.core.models.Snapshot.Meta.app_label
:value: >
   'core'

```{autodoc2-docstring} archivebox.core.models.Snapshot.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.core.models.Snapshot.Meta.verbose_name
:value: >
   'Snapshot'

```{autodoc2-docstring} archivebox.core.models.Snapshot.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.core.models.Snapshot.Meta.verbose_name_plural
:value: >
   'Snapshots'

```{autodoc2-docstring} archivebox.core.models.Snapshot.Meta.verbose_name_plural
```

````

````{py:attribute} indexes
:canonical: archivebox.core.models.Snapshot.Meta.indexes
:type: typing.ClassVar[list[django.db.models.Index]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.Meta.indexes
```

````

````{py:attribute} constraints
:canonical: archivebox.core.models.Snapshot.Meta.constraints
:type: typing.ClassVar[list[django.db.models.BaseConstraint]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot.Meta.constraints
```

````

`````

````{py:method} __str__()
:canonical: archivebox.core.models.Snapshot.__str__

````

````{py:method} crawl_count_subquery(*, status: str | None = None, outer_ref: str = 'pk') -> django.db.models.QuerySet
:canonical: archivebox.core.models.Snapshot.crawl_count_subquery
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.crawl_count_subquery
```

````

````{py:method} crawl_count_expr(*, status: str | None = None, outer_ref: str = 'pk')
:canonical: archivebox.core.models.Snapshot.crawl_count_expr
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.crawl_count_expr
```

````

````{py:method} crawl_total_and_status_counts(crawl_ids: collections.abc.Iterable[typing.Any], *, status: str) -> dict[str, dict[str, int]]
:canonical: archivebox.core.models.Snapshot.crawl_total_and_status_counts
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.crawl_total_and_status_counts
```

````

````{py:method} update_and_requeue(**kwargs) -> bool
:canonical: archivebox.core.models.Snapshot.update_and_requeue

```{autodoc2-docstring} archivebox.core.models.Snapshot.update_and_requeue
```

````

````{py:method} queue_for_extraction(*, when=None) -> bool
:canonical: archivebox.core.models.Snapshot.queue_for_extraction

```{autodoc2-docstring} archivebox.core.models.Snapshot.queue_for_extraction
```

````

````{py:method} pause(*, save: bool = True) -> bool
:canonical: archivebox.core.models.Snapshot.pause

```{autodoc2-docstring} archivebox.core.models.Snapshot.pause
```

````

````{py:method} resume(*, when: datetime.datetime | None = None, save: bool = True) -> bool
:canonical: archivebox.core.models.Snapshot.resume

```{autodoc2-docstring} archivebox.core.models.Snapshot.resume
```

````

````{py:method} restore_paused_scheduler_marker() -> None
:canonical: archivebox.core.models.Snapshot.restore_paused_scheduler_marker

```{autodoc2-docstring} archivebox.core.models.Snapshot.restore_paused_scheduler_marker
```

````

````{py:method} reconcile_parent_lifecycle(*, lock_seconds: int = 60) -> bool | None
:canonical: archivebox.core.models.Snapshot.reconcile_parent_lifecycle

```{autodoc2-docstring} archivebox.core.models.Snapshot.reconcile_parent_lifecycle
```

````

````{py:method} finalize_completed_upload_results() -> int
:canonical: archivebox.core.models.Snapshot.finalize_completed_upload_results

```{autodoc2-docstring} archivebox.core.models.Snapshot.finalize_completed_upload_results
```

````

````{py:method} reset_abandoned_results() -> tuple[int, int]
:canonical: archivebox.core.models.Snapshot.reset_abandoned_results

```{autodoc2-docstring} archivebox.core.models.Snapshot.reset_abandoned_results
```

````

````{py:method} start_processing() -> bool
:canonical: archivebox.core.models.Snapshot.start_processing

```{autodoc2-docstring} archivebox.core.models.Snapshot.start_processing
```

````

````{py:method} seal() -> bool
:canonical: archivebox.core.models.Snapshot.seal

```{autodoc2-docstring} archivebox.core.models.Snapshot.seal
```

````

````{py:method} advance_lifecycle() -> bool
:canonical: archivebox.core.models.Snapshot.advance_lifecycle

```{autodoc2-docstring} archivebox.core.models.Snapshot.advance_lifecycle
```

````

````{py:method} cancel() -> None
:canonical: archivebox.core.models.Snapshot.cancel

```{autodoc2-docstring} archivebox.core.models.Snapshot.cancel
```

````

````{py:method} get_delete_after_config_value()
:canonical: archivebox.core.models.Snapshot.get_delete_after_config_value

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_delete_after_config_value
```

````

````{py:method} missing_delete_at_candidates()
:canonical: archivebox.core.models.Snapshot.missing_delete_at_candidates
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.missing_delete_at_candidates
```

````

````{py:method} is_archivebox_internal_url(url: str, *, config: collections.abc.Mapping[str, typing.Any] | typing.Any | None = None) -> bool
:canonical: archivebox.core.models.Snapshot.is_archivebox_internal_url
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_archivebox_internal_url
```

````

````{py:property} created_by
:canonical: archivebox.core.models.Snapshot.created_by

```{autodoc2-docstring} archivebox.core.models.Snapshot.created_by
```

````

````{py:property} process_set
:canonical: archivebox.core.models.Snapshot.process_set

```{autodoc2-docstring} archivebox.core.models.Snapshot.process_set
```

````

````{py:property} binary_set
:canonical: archivebox.core.models.Snapshot.binary_set

```{autodoc2-docstring} archivebox.core.models.Snapshot.binary_set
```

````

````{py:method} ensure_permissions_config(crawl_permissions: str | None = None) -> bool
:canonical: archivebox.core.models.Snapshot.ensure_permissions_config

```{autodoc2-docstring} archivebox.core.models.Snapshot.ensure_permissions_config
```

````

````{py:method} validate_url_for_archiving(*, config: collections.abc.Mapping[str, typing.Any] | typing.Any | None = None) -> None
:canonical: archivebox.core.models.Snapshot.validate_url_for_archiving

```{autodoc2-docstring} archivebox.core.models.Snapshot.validate_url_for_archiving
```

````

````{py:method} is_internal_input_url() -> bool
:canonical: archivebox.core.models.Snapshot.is_internal_input_url

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_internal_input_url
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.core.models.Snapshot.save

````

````{py:method} _fs_current_version() -> str
:canonical: archivebox.core.models.Snapshot._fs_current_version
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_current_version
```

````

````{py:attribute} _FS_VERSION_MIGRATION_PATHS
:canonical: archivebox.core.models.Snapshot._FS_VERSION_MIGRATION_PATHS
:type: typing.ClassVar[dict[str, str]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.Snapshot._FS_VERSION_MIGRATION_PATHS
```

````

````{py:property} fs_migration_needed
:canonical: archivebox.core.models.Snapshot.fs_migration_needed
:type: bool

```{autodoc2-docstring} archivebox.core.models.Snapshot.fs_migration_needed
```

````

````{py:method} _fs_next_version(version: str) -> str
:canonical: archivebox.core.models.Snapshot._fs_next_version

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_next_version
```

````

````{py:method} is_legacy_archive_dir(path: pathlib.Path) -> bool
:canonical: archivebox.core.models.Snapshot.is_legacy_archive_dir
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_legacy_archive_dir
```

````

````{py:method} migrate_filesystem_to_current_version(source_dir: pathlib.Path | None = None, config: ArchiveBoxBaseConfig | None = None) -> None
:canonical: archivebox.core.models.Snapshot.migrate_filesystem_to_current_version

```{autodoc2-docstring} archivebox.core.models.Snapshot.migrate_filesystem_to_current_version
```

````

````{py:method} _fs_migrate_from_0_7_0_to_0_9_0(source_dir: pathlib.Path | None = None, config: ArchiveBoxBaseConfig | None = None)
:canonical: archivebox.core.models.Snapshot._fs_migrate_from_0_7_0_to_0_9_0

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_migrate_from_0_7_0_to_0_9_0
```

````

````{py:method} _fs_migrate_from_0_8_0_to_0_9_0(source_dir: pathlib.Path | None = None, config: ArchiveBoxBaseConfig | None = None)
:canonical: archivebox.core.models.Snapshot._fs_migrate_from_0_8_0_to_0_9_0

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_migrate_from_0_8_0_to_0_9_0
```

````

````{py:method} _fs_migrate_from_0_9_0_to_0_9_4(source_dir: pathlib.Path | None = None, config: ArchiveBoxBaseConfig | None = None)
:canonical: archivebox.core.models.Snapshot._fs_migrate_from_0_9_0_to_0_9_4

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_migrate_from_0_9_0_to_0_9_4
```

````

````{py:method} hydrate_archiveresult_output_metadata(snapshot_dir: pathlib.Path | None = None) -> int
:canonical: archivebox.core.models.Snapshot.hydrate_archiveresult_output_metadata

```{autodoc2-docstring} archivebox.core.models.Snapshot.hydrate_archiveresult_output_metadata
```

````

````{py:method} _fs_migrate_legacy_to_0_9_0(source_dir: pathlib.Path | None = None, target_dir: pathlib.Path | None = None, config: ArchiveBoxBaseConfig | None = None)
:canonical: archivebox.core.models.Snapshot._fs_migrate_legacy_to_0_9_0

```{autodoc2-docstring} archivebox.core.models.Snapshot._fs_migrate_legacy_to_0_9_0
```

````

````{py:method} _cleanup_old_migration_dir(old_dir: pathlib.Path, new_dir: pathlib.Path)
:canonical: archivebox.core.models.Snapshot._cleanup_old_migration_dir

```{autodoc2-docstring} archivebox.core.models.Snapshot._cleanup_old_migration_dir
```

````

````{py:method} extract_domain_from_url(url: str) -> str
:canonical: archivebox.core.models.Snapshot.extract_domain_from_url
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.extract_domain_from_url
```

````

````{py:method} get_storage_path_for_version(version: str) -> pathlib.Path
:canonical: archivebox.core.models.Snapshot.get_storage_path_for_version

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_storage_path_for_version
```

````

````{py:method} load_from_directory(snapshot_dir: pathlib.Path) -> typing.Optional[archivebox.core.models.Snapshot]
:canonical: archivebox.core.models.Snapshot.load_from_directory
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.load_from_directory
```

````

````{py:method} create_from_directory(snapshot_dir: pathlib.Path) -> typing.Optional[archivebox.core.models.Snapshot]
:canonical: archivebox.core.models.Snapshot.create_from_directory
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.create_from_directory
```

````

````{py:method} _select_best_timestamp(index_timestamp: object | None, folder_name: str) -> str | None
:canonical: archivebox.core.models.Snapshot._select_best_timestamp
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._select_best_timestamp
```

````

````{py:method} _ensure_unique_timestamp(url: str, timestamp: str) -> str
:canonical: archivebox.core.models.Snapshot._ensure_unique_timestamp
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._ensure_unique_timestamp
```

````

````{py:method} _detect_fs_version_from_index(data: dict) -> str
:canonical: archivebox.core.models.Snapshot._detect_fs_version_from_index
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._detect_fs_version_from_index
```

````

````{py:method} reconcile_with_index(output_dir: pathlib.Path | None = None, update_existing_archive_results: bool = True)
:canonical: archivebox.core.models.Snapshot.reconcile_with_index

```{autodoc2-docstring} archivebox.core.models.Snapshot.reconcile_with_index
```

````

````{py:method} reconcile_with_index_json(output_dir: pathlib.Path | None = None, update_existing_archive_results: bool = True)
:canonical: archivebox.core.models.Snapshot.reconcile_with_index_json

```{autodoc2-docstring} archivebox.core.models.Snapshot.reconcile_with_index_json
```

````

````{py:method} _merge_title_from_index(index_data: dict)
:canonical: archivebox.core.models.Snapshot._merge_title_from_index

```{autodoc2-docstring} archivebox.core.models.Snapshot._merge_title_from_index
```

````

````{py:method} _merge_tags_from_index(index_data: dict)
:canonical: archivebox.core.models.Snapshot._merge_tags_from_index

```{autodoc2-docstring} archivebox.core.models.Snapshot._merge_tags_from_index
```

````

````{py:method} _merge_archive_results_from_index(index_data: dict, update_existing: bool = True)
:canonical: archivebox.core.models.Snapshot._merge_archive_results_from_index

```{autodoc2-docstring} archivebox.core.models.Snapshot._merge_archive_results_from_index
```

````

````{py:method} _create_archive_result_if_missing(result_data: dict, existing: dict, update_existing: bool = True)
:canonical: archivebox.core.models.Snapshot._create_archive_result_if_missing

```{autodoc2-docstring} archivebox.core.models.Snapshot._create_archive_result_if_missing
```

````

````{py:method} write_index_json()
:canonical: archivebox.core.models.Snapshot.write_index_json

```{autodoc2-docstring} archivebox.core.models.Snapshot.write_index_json
```

````

````{py:method} write_index_jsonl(output_dir: pathlib.Path | None = None)
:canonical: archivebox.core.models.Snapshot.write_index_jsonl

```{autodoc2-docstring} archivebox.core.models.Snapshot.write_index_jsonl
```

````

````{py:method} read_index_jsonl(output_dir: pathlib.Path | None = None) -> dict
:canonical: archivebox.core.models.Snapshot.read_index_jsonl

```{autodoc2-docstring} archivebox.core.models.Snapshot.read_index_jsonl
```

````

````{py:method} convert_index_json_to_jsonl(output_dir: pathlib.Path | None = None) -> bool
:canonical: archivebox.core.models.Snapshot.convert_index_json_to_jsonl

```{autodoc2-docstring} archivebox.core.models.Snapshot.convert_index_json_to_jsonl
```

````

````{py:method} move_directory_to_invalid(snapshot_dir: pathlib.Path)
:canonical: archivebox.core.models.Snapshot.move_directory_to_invalid
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.move_directory_to_invalid
```

````

````{py:method} find_and_merge_duplicates() -> int
:canonical: archivebox.core.models.Snapshot.find_and_merge_duplicates
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.find_and_merge_duplicates
```

````

````{py:method} _merge_snapshots(snapshots: collections.abc.Sequence[archivebox.core.models.Snapshot])
:canonical: archivebox.core.models.Snapshot._merge_snapshots
:classmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._merge_snapshots
```

````

````{py:property} output_dir_parent
:canonical: archivebox.core.models.Snapshot.output_dir_parent
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.output_dir_parent
```

````

````{py:property} output_dir_name
:canonical: archivebox.core.models.Snapshot.output_dir_name
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.output_dir_name
```

````

````{py:method} archive(overwrite=False, methods=None)
:canonical: archivebox.core.models.Snapshot.archive

```{autodoc2-docstring} archivebox.core.models.Snapshot.archive
```

````

````{py:method} tags_str() -> str | None
:canonical: archivebox.core.models.Snapshot.tags_str

```{autodoc2-docstring} archivebox.core.models.Snapshot.tags_str
```

````

````{py:method} icons(path: str | None = None, prefix: str = '/', quote_paths: bool = False) -> str
:canonical: archivebox.core.models.Snapshot.icons

```{autodoc2-docstring} archivebox.core.models.Snapshot.icons
```

````

````{py:property} api_url
:canonical: archivebox.core.models.Snapshot.api_url
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.api_url
```

````

````{py:method} get_absolute_url()
:canonical: archivebox.core.models.Snapshot.get_absolute_url

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_absolute_url
```

````

````{py:method} domain() -> str
:canonical: archivebox.core.models.Snapshot.domain

```{autodoc2-docstring} archivebox.core.models.Snapshot.domain
```

````

````{py:property} title_stripped
:canonical: archivebox.core.models.Snapshot.title_stripped
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.title_stripped
```

````

````{py:method} _normalize_title_candidate(candidate: str | None, *, snapshot_url: str) -> str
:canonical: archivebox.core.models.Snapshot._normalize_title_candidate
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._normalize_title_candidate
```

````

````{py:property} resolved_title
:canonical: archivebox.core.models.Snapshot.resolved_title
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.resolved_title
```

````

````{py:method} hashes_index() -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.core.models.Snapshot.hashes_index

```{autodoc2-docstring} archivebox.core.models.Snapshot.hashes_index
```

````

````{py:property} output_dir
:canonical: archivebox.core.models.Snapshot.output_dir
:type: pathlib.Path

```{autodoc2-docstring} archivebox.core.models.Snapshot.output_dir
```

````

````{py:method} ensure_crawl_symlink(*, crawl_dir: pathlib.Path | None = None, snapshot_dir: pathlib.Path | None = None) -> None
:canonical: archivebox.core.models.Snapshot.ensure_crawl_symlink

```{autodoc2-docstring} archivebox.core.models.Snapshot.ensure_crawl_symlink
```

````

````{py:method} remove_legacy_archive_symlink() -> None
:canonical: archivebox.core.models.Snapshot.remove_legacy_archive_symlink

```{autodoc2-docstring} archivebox.core.models.Snapshot.remove_legacy_archive_symlink
```

````

````{py:method} legacy_archive_path() -> str
:canonical: archivebox.core.models.Snapshot.legacy_archive_path

```{autodoc2-docstring} archivebox.core.models.Snapshot.legacy_archive_path
```

````

````{py:method} archive_path_from_db() -> str
:canonical: archivebox.core.models.Snapshot.archive_path_from_db

```{autodoc2-docstring} archivebox.core.models.Snapshot.archive_path_from_db
```

````

````{py:method} url_path() -> str
:canonical: archivebox.core.models.Snapshot.url_path

```{autodoc2-docstring} archivebox.core.models.Snapshot.url_path
```

````

````{py:method} archive_path()
:canonical: archivebox.core.models.Snapshot.archive_path

```{autodoc2-docstring} archivebox.core.models.Snapshot.archive_path
```

````

````{py:method} archive_size()
:canonical: archivebox.core.models.Snapshot.archive_size

```{autodoc2-docstring} archivebox.core.models.Snapshot.archive_size
```

````

````{py:method} save_tags(tags: collections.abc.Iterable[str] = ()) -> None
:canonical: archivebox.core.models.Snapshot.save_tags

```{autodoc2-docstring} archivebox.core.models.Snapshot.save_tags
```

````

````{py:method} pending_archiveresults() -> django.db.models.QuerySet[archivebox.core.models.ArchiveResult]
:canonical: archivebox.core.models.Snapshot.pending_archiveresults

```{autodoc2-docstring} archivebox.core.models.Snapshot.pending_archiveresults
```

````

````{py:method} run() -> list[archivebox.core.models.ArchiveResult]
:canonical: archivebox.core.models.Snapshot.run

```{autodoc2-docstring} archivebox.core.models.Snapshot.run
```

````

````{py:method} finalize_output_metadata() -> None
:canonical: archivebox.core.models.Snapshot.finalize_output_metadata

```{autodoc2-docstring} archivebox.core.models.Snapshot.finalize_output_metadata
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.core.models.Snapshot.to_json

```{autodoc2-docstring} archivebox.core.models.Snapshot.to_json
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None, queue_for_extraction: bool = True)
:canonical: archivebox.core.models.Snapshot.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot.from_json
```

````

````{py:method} create_pending_archiveresults(hooks: collections.abc.Iterable[tuple[str, str]] | None = None) -> list[archivebox.core.models.ArchiveResult]
:canonical: archivebox.core.models.Snapshot.create_pending_archiveresults

```{autodoc2-docstring} archivebox.core.models.Snapshot.create_pending_archiveresults
```

````

````{py:method} is_finished_processing() -> bool
:canonical: archivebox.core.models.Snapshot.is_finished_processing

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_finished_processing
```

````

````{py:method} get_progress_stats() -> dict
:canonical: archivebox.core.models.Snapshot.get_progress_stats

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_progress_stats
```

````

````{py:method} retry_failed_archiveresults() -> int
:canonical: archivebox.core.models.Snapshot.retry_failed_archiveresults

```{autodoc2-docstring} archivebox.core.models.Snapshot.retry_failed_archiveresults
```

````

````{py:method} url_hash() -> str
:canonical: archivebox.core.models.Snapshot.url_hash

```{autodoc2-docstring} archivebox.core.models.Snapshot.url_hash
```

````

````{py:method} scheme() -> str
:canonical: archivebox.core.models.Snapshot.scheme

```{autodoc2-docstring} archivebox.core.models.Snapshot.scheme
```

````

````{py:method} path() -> str
:canonical: archivebox.core.models.Snapshot.path

```{autodoc2-docstring} archivebox.core.models.Snapshot.path
```

````

````{py:method} basename() -> str
:canonical: archivebox.core.models.Snapshot.basename

```{autodoc2-docstring} archivebox.core.models.Snapshot.basename
```

````

````{py:method} extension() -> str
:canonical: archivebox.core.models.Snapshot.extension

```{autodoc2-docstring} archivebox.core.models.Snapshot.extension
```

````

````{py:method} base_url() -> str
:canonical: archivebox.core.models.Snapshot.base_url

```{autodoc2-docstring} archivebox.core.models.Snapshot.base_url
```

````

````{py:method} is_static() -> bool
:canonical: archivebox.core.models.Snapshot.is_static

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_static
```

````

````{py:method} is_archived() -> bool
:canonical: archivebox.core.models.Snapshot.is_archived

```{autodoc2-docstring} archivebox.core.models.Snapshot.is_archived
```

````

````{py:method} bookmarked_date() -> str | None
:canonical: archivebox.core.models.Snapshot.bookmarked_date

```{autodoc2-docstring} archivebox.core.models.Snapshot.bookmarked_date
```

````

````{py:method} downloaded_datestr() -> str | None
:canonical: archivebox.core.models.Snapshot.downloaded_datestr

```{autodoc2-docstring} archivebox.core.models.Snapshot.downloaded_datestr
```

````

````{py:method} archive_dates() -> list[datetime.datetime]
:canonical: archivebox.core.models.Snapshot.archive_dates

```{autodoc2-docstring} archivebox.core.models.Snapshot.archive_dates
```

````

````{py:method} oldest_archive_date() -> datetime.datetime | None
:canonical: archivebox.core.models.Snapshot.oldest_archive_date

```{autodoc2-docstring} archivebox.core.models.Snapshot.oldest_archive_date
```

````

````{py:method} newest_archive_date() -> datetime.datetime | None
:canonical: archivebox.core.models.Snapshot.newest_archive_date

```{autodoc2-docstring} archivebox.core.models.Snapshot.newest_archive_date
```

````

````{py:method} num_outputs() -> int
:canonical: archivebox.core.models.Snapshot.num_outputs

```{autodoc2-docstring} archivebox.core.models.Snapshot.num_outputs
```

````

````{py:method} num_failures() -> int
:canonical: archivebox.core.models.Snapshot.num_failures

```{autodoc2-docstring} archivebox.core.models.Snapshot.num_failures
```

````

````{py:method} latest_outputs(status: str | None = None) -> dict[str, typing.Any]
:canonical: archivebox.core.models.Snapshot.latest_outputs

```{autodoc2-docstring} archivebox.core.models.Snapshot.latest_outputs
```

````

````{py:method} discover_outputs(include_filesystem_fallback: bool = True, archive_results: list[archivebox.core.models.Snapshot.discover_outputs.ArchiveResult] | None = None) -> list[dict]
:canonical: archivebox.core.models.Snapshot.discover_outputs

```{autodoc2-docstring} archivebox.core.models.Snapshot.discover_outputs
```

````

````{py:property} static_archive_path
:canonical: archivebox.core.models.Snapshot.static_archive_path
:type: str

```{autodoc2-docstring} archivebox.core.models.Snapshot.static_archive_path
```

````

````{py:method} to_dict(extended: bool = False, static_export: bool = False) -> dict[str, typing.Any]
:canonical: archivebox.core.models.Snapshot.to_dict

```{autodoc2-docstring} archivebox.core.models.Snapshot.to_dict
```

````

````{py:method} to_json_str(indent: int = 4) -> str
:canonical: archivebox.core.models.Snapshot.to_json_str

```{autodoc2-docstring} archivebox.core.models.Snapshot.to_json_str
```

````

````{py:method} to_csv(cols: list[str] | None = None, separator: str = ',', ljust: int = 0) -> str
:canonical: archivebox.core.models.Snapshot.to_csv

```{autodoc2-docstring} archivebox.core.models.Snapshot.to_csv
```

````

````{py:method} write_json_details(out_dir: pathlib.Path | str | None = None) -> None
:canonical: archivebox.core.models.Snapshot.write_json_details

```{autodoc2-docstring} archivebox.core.models.Snapshot.write_json_details
```

````

````{py:method} get_html_details_context(request=None, *, static_export_dir: pathlib.Path | None = None) -> dict[str, typing.Any]
:canonical: archivebox.core.models.Snapshot.get_html_details_context

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_html_details_context
```

````

````{py:method} write_html_details(out_dir: pathlib.Path | str | None = None) -> None
:canonical: archivebox.core.models.Snapshot.write_html_details

```{autodoc2-docstring} archivebox.core.models.Snapshot.write_html_details
```

````

````{py:method} get_detail_page_auxiliary_items(outputs: list[dict] | None = None, hidden_card_plugins: set[str] | None = None, archive_results: list[archivebox.core.models.Snapshot.get_detail_page_auxiliary_items.ArchiveResult] | None = None) -> tuple[list[dict[str, object]], list[dict[str, object]]]
:canonical: archivebox.core.models.Snapshot.get_detail_page_auxiliary_items

```{autodoc2-docstring} archivebox.core.models.Snapshot.get_detail_page_auxiliary_items
```

````

````{py:method} _ts_to_date_str(dt: datetime.datetime | None) -> str | None
:canonical: archivebox.core.models.Snapshot._ts_to_date_str
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.Snapshot._ts_to_date_str
```

````

``````

``````{py:class} ArchiveResult(*args, **kwargs)
:canonical: archivebox.core.models.ArchiveResult

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir`, {py:obj}`archivebox.base_models.models.ModelWithNotes`

`````{py:class} StatusChoices()
:canonical: archivebox.core.models.ArchiveResult.StatusChoices

Bases: {py:obj}`django.db.models.TextChoices`

````{py:attribute} QUEUED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.QUEUED
:value: >
   ('queued', 'Queued')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.QUEUED
```

````

````{py:attribute} STARTED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.STARTED
:value: >
   ('started', 'Started')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.STARTED
```

````

````{py:attribute} PAUSED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.PAUSED
:value: >
   ('paused', 'Paused')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.PAUSED
```

````

````{py:attribute} BACKOFF
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.BACKOFF
:value: >
   ('backoff', 'Waiting to retry')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.BACKOFF
```

````

````{py:attribute} SUCCEEDED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.SUCCEEDED
:value: >
   ('succeeded', 'Succeeded')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.SUCCEEDED
```

````

````{py:attribute} FAILED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.FAILED
:value: >
   ('failed', 'Failed')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.FAILED
```

````

````{py:attribute} SKIPPED
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.SKIPPED
:value: >
   ('skipped', 'Skipped')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.SKIPPED
```

````

````{py:attribute} NORESULTS
:canonical: archivebox.core.models.ArchiveResult.StatusChoices.NORESULTS
:value: >
   ('noresults', 'No Results')

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.StatusChoices.NORESULTS
```

````

`````

````{py:attribute} INITIAL_STATE
:canonical: archivebox.core.models.ArchiveResult.INITIAL_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.INITIAL_STATE
```

````

````{py:attribute} ACTIVE_STATE
:canonical: archivebox.core.models.ArchiveResult.ACTIVE_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.ACTIVE_STATE
```

````

````{py:attribute} FINAL_STATES
:canonical: archivebox.core.models.ArchiveResult.FINAL_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.FINAL_STATES
```

````

````{py:attribute} FINAL_OR_ACTIVE_STATES
:canonical: archivebox.core.models.ArchiveResult.FINAL_OR_ACTIVE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.FINAL_OR_ACTIVE_STATES
```

````

````{py:attribute} delete_after_final_statuses
:canonical: archivebox.core.models.ArchiveResult.delete_after_final_statuses
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.delete_after_final_statuses
```

````

````{py:method} normalize_status(status: str | None) -> str
:canonical: archivebox.core.models.ArchiveResult.normalize_status
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.normalize_status
```

````

````{py:method} output_files_upload_complete(output_files: dict[str, dict[str, typing.Any]]) -> bool
:canonical: archivebox.core.models.ArchiveResult.output_files_upload_complete
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_files_upload_complete
```

````

````{py:method} get_plugin_choices()
:canonical: archivebox.core.models.ArchiveResult.get_plugin_choices
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.get_plugin_choices
```

````

````{py:method} snapshot_count_subquery(*, status: str | None = None, outer_ref: str = 'pk') -> django.db.models.QuerySet
:canonical: archivebox.core.models.ArchiveResult.snapshot_count_subquery
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_count_subquery
```

````

````{py:method} snapshot_half_count_subquery(*, outer_ref: str = 'snapshot_id') -> django.db.models.QuerySet
:canonical: archivebox.core.models.ArchiveResult.snapshot_half_count_subquery
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_half_count_subquery
```

````

````{py:method} snapshot_count_expr(*, status: str | None = None, outer_ref: str = 'pk')
:canonical: archivebox.core.models.ArchiveResult.snapshot_count_expr
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_count_expr
```

````

````{py:method} status_counts(queryset: django.db.models.QuerySet | None = None, statuses: collections.abc.Iterable[str] | None = None) -> dict[str, int]
:canonical: archivebox.core.models.ArchiveResult.status_counts
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.status_counts
```

````

````{py:method} snapshot_ids_with_majority_status(status: str | collections.abc.Iterable[str]) -> django.db.models.QuerySet
:canonical: archivebox.core.models.ArchiveResult.snapshot_ids_with_majority_status
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_ids_with_majority_status
```

````

````{py:attribute} id
:canonical: archivebox.core.models.ArchiveResult.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.id
```

````

````{py:attribute} created_at
:canonical: archivebox.core.models.ArchiveResult.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.core.models.ArchiveResult.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.modified_at
```

````

````{py:attribute} snapshot
:canonical: archivebox.core.models.ArchiveResult.snapshot
:type: archivebox.core.models.Snapshot
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot
```

````

````{py:attribute} plugin
:canonical: archivebox.core.models.ArchiveResult.plugin
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.plugin
```

````

````{py:attribute} hook_name
:canonical: archivebox.core.models.ArchiveResult.hook_name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.hook_name
```

````

````{py:attribute} process
:canonical: archivebox.core.models.ArchiveResult.process
:value: >
   'OneToOneField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.process
```

````

````{py:attribute} output_str
:canonical: archivebox.core.models.ArchiveResult.output_str
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_str
```

````

````{py:attribute} output_json
:canonical: archivebox.core.models.ArchiveResult.output_json
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_json
```

````

````{py:attribute} output_files
:canonical: archivebox.core.models.ArchiveResult.output_files
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_files
```

````

````{py:attribute} output_size
:canonical: archivebox.core.models.ArchiveResult.output_size
:value: >
   'BigIntegerField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_size
```

````

````{py:attribute} output_mimetypes
:canonical: archivebox.core.models.ArchiveResult.output_mimetypes
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_mimetypes
```

````

````{py:attribute} start_ts
:canonical: archivebox.core.models.ArchiveResult.start_ts
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.start_ts
```

````

````{py:attribute} end_ts
:canonical: archivebox.core.models.ArchiveResult.end_ts
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.end_ts
```

````

````{py:attribute} status
:canonical: archivebox.core.models.ArchiveResult.status
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.core.models.ArchiveResult.retry_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.retry_at
```

````

````{py:attribute} notes
:canonical: archivebox.core.models.ArchiveResult.notes
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.notes
```

````

````{py:attribute} snapshot_id
:canonical: archivebox.core.models.ArchiveResult.snapshot_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_id
```

````

````{py:attribute} process_id
:canonical: archivebox.core.models.ArchiveResult.process_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.process_id
```

````

`````{py:class} Meta
:canonical: archivebox.core.models.ArchiveResult.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter.Meta`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir.Meta`, {py:obj}`archivebox.base_models.models.ModelWithNotes.Meta`

````{py:attribute} app_label
:canonical: archivebox.core.models.ArchiveResult.Meta.app_label
:value: >
   'core'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.core.models.ArchiveResult.Meta.verbose_name
:value: >
   'Archive Result'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.core.models.ArchiveResult.Meta.verbose_name_plural
:value: >
   'Archive Results'

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.Meta.verbose_name_plural
```

````

````{py:attribute} indexes
:canonical: archivebox.core.models.ArchiveResult.Meta.indexes
:type: typing.ClassVar[list[django.db.models.Index]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.Meta.indexes
```

````

````{py:attribute} constraints
:canonical: archivebox.core.models.ArchiveResult.Meta.constraints
:type: typing.ClassVar[list[django.db.models.BaseConstraint]]
:value: >
   None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.Meta.constraints
```

````

`````

````{py:method} __str__()
:canonical: archivebox.core.models.ArchiveResult.__str__

````

````{py:method} _format_output_line_for_display(line: str) -> str
:canonical: archivebox.core.models.ArchiveResult._format_output_line_for_display
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._format_output_line_for_display
```

````

````{py:method} output_str_for_display() -> str
:canonical: archivebox.core.models.ArchiveResult.output_str_for_display

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_str_for_display
```

````

````{py:method} get_delete_after_config_value()
:canonical: archivebox.core.models.ArchiveResult.get_delete_after_config_value

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.get_delete_after_config_value
```

````

````{py:method} missing_delete_at_candidates()
:canonical: archivebox.core.models.ArchiveResult.missing_delete_at_candidates
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.missing_delete_at_candidates
```

````

````{py:property} created_by
:canonical: archivebox.core.models.ArchiveResult.created_by

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.created_by
```

````

````{py:method} to_json(*, snapshot_output_dir: pathlib.Path | None = None) -> dict
:canonical: archivebox.core.models.ArchiveResult.to_json

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.to_json
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None)
:canonical: archivebox.core.models.ArchiveResult.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.from_json
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.core.models.ArchiveResult.save

````

````{py:method} schedule_delete_cleanup(*, using: str | None = None) -> None
:canonical: archivebox.core.models.ArchiveResult.schedule_delete_cleanup

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.schedule_delete_cleanup
```

````

````{py:method} refresh_snapshot_output_sizes(snapshot_ids)
:canonical: archivebox.core.models.ArchiveResult.refresh_snapshot_output_sizes
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.refresh_snapshot_output_sizes
```

````

````{py:method} snapshot_dir()
:canonical: archivebox.core.models.ArchiveResult.snapshot_dir

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.snapshot_dir
```

````

````{py:method} url()
:canonical: archivebox.core.models.ArchiveResult.url

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.url
```

````

````{py:property} api_url
:canonical: archivebox.core.models.ArchiveResult.api_url
:type: str

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.api_url
```

````

````{py:method} get_absolute_url()
:canonical: archivebox.core.models.ArchiveResult.get_absolute_url

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.get_absolute_url
```

````

````{py:method} reset_for_retry(*, save: bool = True) -> None
:canonical: archivebox.core.models.ArchiveResult.reset_for_retry

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.reset_for_retry
```

````

````{py:property} is_paused
:canonical: archivebox.core.models.ArchiveResult.is_paused
:type: bool

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.is_paused
```

````

````{py:method} pause_queryset(queryset) -> int
:canonical: archivebox.core.models.ArchiveResult.pause_queryset
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.pause_queryset
```

````

````{py:method} resume_queryset(queryset, *, when: datetime.datetime | None = None) -> int
:canonical: archivebox.core.models.ArchiveResult.resume_queryset
:classmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.resume_queryset
```

````

````{py:method} pause(*, save: bool = True) -> bool
:canonical: archivebox.core.models.ArchiveResult.pause

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.pause
```

````

````{py:method} resume(*, when: datetime.datetime | None = None, save: bool = True) -> bool
:canonical: archivebox.core.models.ArchiveResult.resume

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.resume
```

````

````{py:property} plugin_module
:canonical: archivebox.core.models.ArchiveResult.plugin_module
:type: typing.Any | None

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.plugin_module
```

````

````{py:method} _normalize_output_files(raw_output_files: typing.Any) -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.core.models.ArchiveResult._normalize_output_files
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._normalize_output_files
```

````

````{py:method} _coerce_output_file_size(value: typing.Any) -> int
:canonical: archivebox.core.models.ArchiveResult._coerce_output_file_size
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._coerce_output_file_size
```

````

````{py:method} output_file_map() -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.core.models.ArchiveResult.output_file_map

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_file_map
```

````

````{py:method} output_file_paths() -> list[str]
:canonical: archivebox.core.models.ArchiveResult.output_file_paths

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_file_paths
```

````

````{py:method} output_file_count() -> int
:canonical: archivebox.core.models.ArchiveResult.output_file_count

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_file_count
```

````

````{py:method} output_size_from_files() -> int
:canonical: archivebox.core.models.ArchiveResult.output_size_from_files

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_size_from_files
```

````

````{py:method} update_output_metadata_from_filesystem(snapshot_dir: pathlib.Path | None = None, save: bool = True) -> bool
:canonical: archivebox.core.models.ArchiveResult.update_output_metadata_from_filesystem

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.update_output_metadata_from_filesystem
```

````

````{py:method} output_exists() -> bool
:canonical: archivebox.core.models.ArchiveResult.output_exists

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_exists
```

````

````{py:method} _looks_like_output_path(raw_output: str | None, plugin_name: str | None = None) -> bool
:canonical: archivebox.core.models.ArchiveResult._looks_like_output_path
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._looks_like_output_path
```

````

````{py:method} _existing_output_path(raw_output: str | None) -> str | None
:canonical: archivebox.core.models.ArchiveResult._existing_output_path

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._existing_output_path
```

````

````{py:method} _fallback_output_file_path(output_file_paths: collections.abc.Sequence[str], plugin_name: str | None = None, output_file_map: dict[str, dict[str, typing.Any]] | None = None) -> str | None
:canonical: archivebox.core.models.ArchiveResult._fallback_output_file_path
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._fallback_output_file_path
```

````

````{py:method} _find_best_output_file(dir_path: pathlib.Path, plugin_name: str | None = None) -> pathlib.Path | None
:canonical: archivebox.core.models.ArchiveResult._find_best_output_file
:staticmethod:

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._find_best_output_file
```

````

````{py:method} embed_path_db(output_file_map: dict[str, dict[str, typing.Any]] | None = None) -> str | None
:canonical: archivebox.core.models.ArchiveResult.embed_path_db

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.embed_path_db
```

````

````{py:method} embed_path() -> str | None
:canonical: archivebox.core.models.ArchiveResult.embed_path

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.embed_path
```

````

````{py:property} output_dir_name
:canonical: archivebox.core.models.ArchiveResult.output_dir_name
:type: str

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_dir_name
```

````

````{py:property} output_dir_parent
:canonical: archivebox.core.models.ArchiveResult.output_dir_parent
:type: str

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_dir_parent
```

````

````{py:property} process_record
:canonical: archivebox.core.models.ArchiveResult.process_record

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.process_record
```

````

````{py:property} pwd
:canonical: archivebox.core.models.ArchiveResult.pwd
:type: str

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.pwd
```

````

````{py:property} cmd
:canonical: archivebox.core.models.ArchiveResult.cmd
:type: list

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.cmd
```

````

````{py:property} cmd_version
:canonical: archivebox.core.models.ArchiveResult.cmd_version
:type: str

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.cmd_version
```

````

````{py:property} binary
:canonical: archivebox.core.models.ArchiveResult.binary

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.binary
```

````

````{py:property} iface
:canonical: archivebox.core.models.ArchiveResult.iface

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.iface
```

````

````{py:property} machine
:canonical: archivebox.core.models.ArchiveResult.machine

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.machine
```

````

````{py:property} timeout
:canonical: archivebox.core.models.ArchiveResult.timeout
:type: int

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.timeout
```

````

````{py:method} save_search_index()
:canonical: archivebox.core.models.ArchiveResult.save_search_index

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.save_search_index
```

````

````{py:method} _set_binary_from_cmd(cmd: list) -> None
:canonical: archivebox.core.models.ArchiveResult._set_binary_from_cmd

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._set_binary_from_cmd
```

````

````{py:method} _url_passes_filters(url: str) -> bool
:canonical: archivebox.core.models.ArchiveResult._url_passes_filters

```{autodoc2-docstring} archivebox.core.models.ArchiveResult._url_passes_filters
```

````

````{py:property} output_dir
:canonical: archivebox.core.models.ArchiveResult.output_dir
:type: pathlib.Path

```{autodoc2-docstring} archivebox.core.models.ArchiveResult.output_dir
```

````

``````
