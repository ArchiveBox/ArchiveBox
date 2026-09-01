# {py:mod}`archivebox.crawls.models`

```{py:module} archivebox.crawls.models
```

```{autodoc2-docstring} archivebox.crawls.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CrawlSchedule <archivebox.crawls.models.CrawlSchedule>`
  -
* - {py:obj}`Crawl <archivebox.crawls.models.Crawl>`
  -
````

### API

``````{py:class} CrawlSchedule(*args, **kwargs)
:canonical: archivebox.crawls.models.CrawlSchedule

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID`, {py:obj}`archivebox.base_models.models.ModelWithNotes`

````{py:attribute} id
:canonical: archivebox.crawls.models.CrawlSchedule.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.id
```

````

````{py:attribute} created_at
:canonical: archivebox.crawls.models.CrawlSchedule.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.created_at
```

````

````{py:attribute} created_by
:canonical: archivebox.crawls.models.CrawlSchedule.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.created_by
```

````

````{py:attribute} modified_at
:canonical: archivebox.crawls.models.CrawlSchedule.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.modified_at
```

````

````{py:attribute} template
:canonical: archivebox.crawls.models.CrawlSchedule.template
:type: Crawl
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.template
```

````

````{py:attribute} schedule
:canonical: archivebox.crawls.models.CrawlSchedule.schedule
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.schedule
```

````

````{py:attribute} is_enabled
:canonical: archivebox.crawls.models.CrawlSchedule.is_enabled
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.is_enabled
```

````

````{py:attribute} config
:canonical: archivebox.crawls.models.CrawlSchedule.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.config
```

````

````{py:attribute} label
:canonical: archivebox.crawls.models.CrawlSchedule.label
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.label
```

````

````{py:attribute} notes
:canonical: archivebox.crawls.models.CrawlSchedule.notes
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.notes
```

````

````{py:attribute} crawl_set
:canonical: archivebox.crawls.models.CrawlSchedule.crawl_set
:type: django.db.models.Manager[Crawl]
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.crawl_set
```

````

`````{py:class} Meta
:canonical: archivebox.crawls.models.CrawlSchedule.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithUUID.Meta`, {py:obj}`archivebox.base_models.models.ModelWithNotes.Meta`

````{py:attribute} app_label
:canonical: archivebox.crawls.models.CrawlSchedule.Meta.app_label
:value: >
   'crawls'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.crawls.models.CrawlSchedule.Meta.verbose_name
:value: >
   'Scheduled Crawl'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.crawls.models.CrawlSchedule.Meta.verbose_name_plural
:value: >
   'Scheduled Crawls'

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.Meta.verbose_name_plural
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.crawls.models.CrawlSchedule.__str__

````

````{py:property} api_url
:canonical: archivebox.crawls.models.CrawlSchedule.api_url
:type: str

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.api_url
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.crawls.models.CrawlSchedule.save

````

````{py:property} last_run_at
:canonical: archivebox.crawls.models.CrawlSchedule.last_run_at

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.last_run_at
```

````

````{py:property} next_run_at
:canonical: archivebox.crawls.models.CrawlSchedule.next_run_at

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.next_run_at
```

````

````{py:method} is_due(now=None) -> bool
:canonical: archivebox.crawls.models.CrawlSchedule.is_due

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.is_due
```

````

````{py:method} enqueue(queued_at=None) -> archivebox.crawls.models.Crawl
:canonical: archivebox.crawls.models.CrawlSchedule.enqueue

```{autodoc2-docstring} archivebox.crawls.models.CrawlSchedule.enqueue
```

````

``````

``````{py:class} Crawl(*args, **kwargs)
:canonical: archivebox.crawls.models.Crawl

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir`, {py:obj}`archivebox.base_models.models.ModelWithConfig`, {py:obj}`archivebox.base_models.models.ModelWithHealthStats`, {py:obj}`archivebox.workers.models.ModelWithQueue`

````{py:attribute} id
:canonical: archivebox.crawls.models.Crawl.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.id
```

````

````{py:attribute} created_at
:canonical: archivebox.crawls.models.Crawl.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.created_at
```

````

````{py:attribute} created_by
:canonical: archivebox.crawls.models.Crawl.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.created_by
```

````

````{py:attribute} modified_at
:canonical: archivebox.crawls.models.Crawl.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.modified_at
```

````

````{py:attribute} urls
:canonical: archivebox.crawls.models.Crawl.urls
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.urls
```

````

````{py:attribute} config
:canonical: archivebox.crawls.models.Crawl.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.config
```

````

````{py:attribute} permissions
:canonical: archivebox.crawls.models.Crawl.permissions
:value: >
   'GeneratedField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.permissions
```

````

````{py:attribute} max_depth
:canonical: archivebox.crawls.models.Crawl.max_depth
:value: >
   'PositiveSmallIntegerField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.max_depth
```

````

````{py:attribute} tags_str
:canonical: archivebox.crawls.models.Crawl.tags_str
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.tags_str
```

````

````{py:attribute} persona
:canonical: archivebox.crawls.models.Crawl.persona
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.persona
```

````

````{py:attribute} label
:canonical: archivebox.crawls.models.Crawl.label
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.label
```

````

````{py:attribute} notes
:canonical: archivebox.crawls.models.Crawl.notes
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.notes
```

````

````{py:attribute} schedule
:canonical: archivebox.crawls.models.Crawl.schedule
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.schedule
```

````

````{py:attribute} status
:canonical: archivebox.crawls.models.Crawl.status
:value: >
   'StatusField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.crawls.models.Crawl.retry_at
:value: >
   'RetryAtField(...)'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.retry_at
```

````

````{py:attribute} retry_at_field_name
:canonical: archivebox.crawls.models.Crawl.retry_at_field_name
:value: >
   'retry_at'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.retry_at_field_name
```

````

````{py:attribute} state_field_name
:canonical: archivebox.crawls.models.Crawl.state_field_name
:value: >
   'status'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.state_field_name
```

````

````{py:attribute} StatusChoices
:canonical: archivebox.crawls.models.Crawl.StatusChoices
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.StatusChoices
```

````

````{py:attribute} INITIAL_STATE
:canonical: archivebox.crawls.models.Crawl.INITIAL_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.INITIAL_STATE
```

````

````{py:attribute} ACTIVE_STATE
:canonical: archivebox.crawls.models.Crawl.ACTIVE_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.ACTIVE_STATE
```

````

````{py:attribute} FINAL_STATES
:canonical: archivebox.crawls.models.Crawl.FINAL_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.models.Crawl.FINAL_STATES
```

````

````{py:attribute} FINAL_OR_ACTIVE_STATES
:canonical: archivebox.crawls.models.Crawl.FINAL_OR_ACTIVE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.models.Crawl.FINAL_OR_ACTIVE_STATES
```

````

````{py:attribute} active_state
:canonical: archivebox.crawls.models.Crawl.active_state
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.active_state
```

````

````{py:attribute} delete_after_final_statuses
:canonical: archivebox.crawls.models.Crawl.delete_after_final_statuses
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.models.Crawl.delete_after_final_statuses
```

````

````{py:attribute} RUNNABLE_STATES
:canonical: archivebox.crawls.models.Crawl.RUNNABLE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.models.Crawl.RUNNABLE_STATES
```

````

````{py:attribute} INACTIVE_STATES
:canonical: archivebox.crawls.models.Crawl.INACTIVE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.models.Crawl.INACTIVE_STATES
```

````

````{py:attribute} schedule_id
:canonical: archivebox.crawls.models.Crawl.schedule_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.schedule_id
```

````

````{py:attribute} snapshot_set
:canonical: archivebox.crawls.models.Crawl.snapshot_set
:type: django.db.models.Manager[archivebox.core.models.Snapshot]
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.snapshot_set
```

````

`````{py:class} Meta
:canonical: archivebox.crawls.models.Crawl.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter.Meta`, {py:obj}`archivebox.base_models.models.ModelWithOutputDir.Meta`, {py:obj}`archivebox.base_models.models.ModelWithConfig.Meta`, {py:obj}`archivebox.base_models.models.ModelWithHealthStats.Meta`, {py:obj}`archivebox.workers.models.ModelWithQueue.Meta`

````{py:attribute} app_label
:canonical: archivebox.crawls.models.Crawl.Meta.app_label
:value: >
   'crawls'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.crawls.models.Crawl.Meta.verbose_name
:value: >
   'Crawl'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.crawls.models.Crawl.Meta.verbose_name_plural
:value: >
   'Crawls'

```{autodoc2-docstring} archivebox.crawls.models.Crawl.Meta.verbose_name_plural
```

````

````{py:attribute} indexes
:canonical: archivebox.crawls.models.Crawl.Meta.indexes
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.models.Crawl.Meta.indexes
```

````

`````

````{py:method} __str__()
:canonical: archivebox.crawls.models.Crawl.__str__

````

````{py:method} get_delete_after_config_value()
:canonical: archivebox.crawls.models.Crawl.get_delete_after_config_value

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_delete_after_config_value
```

````

````{py:method} pause(*, save: bool = True) -> bool
:canonical: archivebox.crawls.models.Crawl.pause

```{autodoc2-docstring} archivebox.crawls.models.Crawl.pause
```

````

````{py:method} resume(*, when=None, save: bool = True) -> bool
:canonical: archivebox.crawls.models.Crawl.resume

```{autodoc2-docstring} archivebox.crawls.models.Crawl.resume
```

````

````{py:method} cancel() -> None
:canonical: archivebox.crawls.models.Crawl.cancel

```{autodoc2-docstring} archivebox.crawls.models.Crawl.cancel
```

````

````{py:method} schedule_child_snapshots_for_sealing() -> int
:canonical: archivebox.crawls.models.Crawl.schedule_child_snapshots_for_sealing

```{autodoc2-docstring} archivebox.crawls.models.Crawl.schedule_child_snapshots_for_sealing
```

````

````{py:method} schedule_child_snapshots_for_pause() -> int
:canonical: archivebox.crawls.models.Crawl.schedule_child_snapshots_for_pause

```{autodoc2-docstring} archivebox.crawls.models.Crawl.schedule_child_snapshots_for_pause
```

````

````{py:method} missing_delete_at_candidates()
:canonical: archivebox.crawls.models.Crawl.missing_delete_at_candidates
:classmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.missing_delete_at_candidates
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.crawls.models.Crawl.save

````

````{py:method} update_child_snapshot_permissions(old_permissions: str | None, new_permissions: str | None) -> int
:canonical: archivebox.crawls.models.Crawl.update_child_snapshot_permissions

```{autodoc2-docstring} archivebox.crawls.models.Crawl.update_child_snapshot_permissions
```

````

````{py:property} api_url
:canonical: archivebox.crawls.models.Crawl.api_url
:type: str

```{autodoc2-docstring} archivebox.crawls.models.Crawl.api_url
```

````

````{py:method} parse_tag_names(tags: collections.abc.Iterable[str] | str, *, pattern: str = ',') -> list[str]
:canonical: archivebox.crawls.models.Crawl.parse_tag_names
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.parse_tag_names
```

````

````{py:method} current_tag_names() -> list[str]
:canonical: archivebox.crawls.models.Crawl.current_tag_names

```{autodoc2-docstring} archivebox.crawls.models.Crawl.current_tag_names
```

````

````{py:method} apply_snapshot_tag_diff(*, added_tag_names: collections.abc.Iterable[str], removed_tag_names: collections.abc.Iterable[str]) -> None
:canonical: archivebox.crawls.models.Crawl.apply_snapshot_tag_diff

```{autodoc2-docstring} archivebox.crawls.models.Crawl.apply_snapshot_tag_diff
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.crawls.models.Crawl.to_json

```{autodoc2-docstring} archivebox.crawls.models.Crawl.to_json
```

````

````{py:method} from_json(record: dict, overrides: dict | None = None)
:canonical: archivebox.crawls.models.Crawl.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.from_json
```

````

````{py:property} output_dir
:canonical: archivebox.crawls.models.Crawl.output_dir
:type: pathlib.Path

```{autodoc2-docstring} archivebox.crawls.models.Crawl.output_dir
```

````

````{py:method} get_urls_list() -> list[str]
:canonical: archivebox.crawls.models.Crawl.get_urls_list

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_urls_list
```

````

````{py:method} has_internal_input_root() -> bool
:canonical: archivebox.crawls.models.Crawl.has_internal_input_root

```{autodoc2-docstring} archivebox.crawls.models.Crawl.has_internal_input_root
```

````

````{py:method} normalize_domain(value: str) -> str
:canonical: archivebox.crawls.models.Crawl.normalize_domain
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.normalize_domain
```

````

````{py:method} split_filter_patterns(value) -> list[str]
:canonical: archivebox.crawls.models.Crawl.split_filter_patterns
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.split_filter_patterns
```

````

````{py:method} _pattern_matches_url(url: str, pattern: str) -> bool
:canonical: archivebox.crawls.models.Crawl._pattern_matches_url
:classmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl._pattern_matches_url
```

````

````{py:method} get_current_config(*, refresh: bool = False) -> dict[str, typing.Any]
:canonical: archivebox.crawls.models.Crawl.get_current_config

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_current_config
```

````

````{py:method} get_url_allowlist(*, use_effective_config: bool = False, snapshot=None) -> list[str]
:canonical: archivebox.crawls.models.Crawl.get_url_allowlist

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_url_allowlist
```

````

````{py:method} get_url_denylist(*, use_effective_config: bool = False, snapshot=None) -> list[str]
:canonical: archivebox.crawls.models.Crawl.get_url_denylist

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_url_denylist
```

````

````{py:method} url_passes_filters(url: str, *, snapshot=None, use_effective_config: bool = True) -> bool
:canonical: archivebox.crawls.models.Crawl.url_passes_filters

```{autodoc2-docstring} archivebox.crawls.models.Crawl.url_passes_filters
```

````

````{py:method} url_passes_compiled_filters(url: str, *, allowlist: list[str], denylist: list[str]) -> bool
:canonical: archivebox.crawls.models.Crawl.url_passes_compiled_filters

```{autodoc2-docstring} archivebox.crawls.models.Crawl.url_passes_compiled_filters
```

````

````{py:method} set_url_filters(allowlist, denylist) -> None
:canonical: archivebox.crawls.models.Crawl.set_url_filters

```{autodoc2-docstring} archivebox.crawls.models.Crawl.set_url_filters
```

````

````{py:method} apply_crawl_config_filters() -> dict[str, int]
:canonical: archivebox.crawls.models.Crawl.apply_crawl_config_filters

```{autodoc2-docstring} archivebox.crawls.models.Crawl.apply_crawl_config_filters
```

````

````{py:method} _iter_url_lines() -> list[tuple[str, str]]
:canonical: archivebox.crawls.models.Crawl._iter_url_lines

```{autodoc2-docstring} archivebox.crawls.models.Crawl._iter_url_lines
```

````

````{py:method} count_urls_for_limit() -> int
:canonical: archivebox.crawls.models.Crawl.count_urls_for_limit

```{autodoc2-docstring} archivebox.crawls.models.Crawl.count_urls_for_limit
```

````

````{py:method} remaining_url_capacity() -> int | None
:canonical: archivebox.crawls.models.Crawl.remaining_url_capacity

```{autodoc2-docstring} archivebox.crawls.models.Crawl.remaining_url_capacity
```

````

````{py:method} has_remaining_url_capacity() -> bool
:canonical: archivebox.crawls.models.Crawl.has_remaining_url_capacity

```{autodoc2-docstring} archivebox.crawls.models.Crawl.has_remaining_url_capacity
```

````

````{py:method} remaining_snapshot_capacity() -> int | None
:canonical: archivebox.crawls.models.Crawl.remaining_snapshot_capacity

```{autodoc2-docstring} archivebox.crawls.models.Crawl.remaining_snapshot_capacity
```

````

````{py:method} has_remaining_snapshot_capacity() -> bool
:canonical: archivebox.crawls.models.Crawl.has_remaining_snapshot_capacity

```{autodoc2-docstring} archivebox.crawls.models.Crawl.has_remaining_snapshot_capacity
```

````

````{py:method} prune_urls(predicate) -> list[str]
:canonical: archivebox.crawls.models.Crawl.prune_urls

```{autodoc2-docstring} archivebox.crawls.models.Crawl.prune_urls
```

````

````{py:method} prune_url(url: str) -> int
:canonical: archivebox.crawls.models.Crawl.prune_url

```{autodoc2-docstring} archivebox.crawls.models.Crawl.prune_url
```

````

````{py:method} exclude_domain(domain: str) -> dict[str, int | str | bool]
:canonical: archivebox.crawls.models.Crawl.exclude_domain

```{autodoc2-docstring} archivebox.crawls.models.Crawl.exclude_domain
```

````

````{py:method} get_system_task() -> str | None
:canonical: archivebox.crawls.models.Crawl.get_system_task

```{autodoc2-docstring} archivebox.crawls.models.Crawl.get_system_task
```

````

````{py:method} resolve_persona()
:canonical: archivebox.crawls.models.Crawl.resolve_persona

```{autodoc2-docstring} archivebox.crawls.models.Crawl.resolve_persona
```

````

````{py:method} _config_value(config: collections.abc.Mapping[str, typing.Any] | typing.Any, key: str, default: typing.Any = None) -> typing.Any
:canonical: archivebox.crawls.models.Crawl._config_value
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl._config_value
```

````

````{py:method} create_scheduler_row(**kwargs) -> archivebox.crawls.models.Crawl
:canonical: archivebox.crawls.models.Crawl.create_scheduler_row
:classmethod:

```{autodoc2-docstring} archivebox.crawls.models.Crawl.create_scheduler_row
```

````

````{py:method} limit_stop_reason(*, config: collections.abc.Mapping[str, typing.Any] | typing.Any | None = None, output_dir: pathlib.Path | None = None, num_snapshots: int | None = None) -> str
:canonical: archivebox.crawls.models.Crawl.limit_stop_reason

```{autodoc2-docstring} archivebox.crawls.models.Crawl.limit_stop_reason
```

````

````{py:method} lifecycle_stop_reason(*, num_snapshots: int | None = None, num_sealed_snapshots: int | None = None) -> str
:canonical: archivebox.crawls.models.Crawl.lifecycle_stop_reason

```{autodoc2-docstring} archivebox.crawls.models.Crawl.lifecycle_stop_reason
```

````

````{py:method} stop_reason(*, config: collections.abc.Mapping[str, typing.Any] | typing.Any | None = None, output_dir: pathlib.Path | None = None, num_snapshots: int | None = None, num_sealed_snapshots: int | None = None) -> str
:canonical: archivebox.crawls.models.Crawl.stop_reason

```{autodoc2-docstring} archivebox.crawls.models.Crawl.stop_reason
```

````

````{py:method} add_url(entry: dict) -> bool
:canonical: archivebox.crawls.models.Crawl.add_url

```{autodoc2-docstring} archivebox.crawls.models.Crawl.add_url
```

````

````{py:method} create_snapshots_from_urls() -> list[archivebox.core.models.Snapshot]
:canonical: archivebox.crawls.models.Crawl.create_snapshots_from_urls

```{autodoc2-docstring} archivebox.crawls.models.Crawl.create_snapshots_from_urls
```

````

````{py:method} create_discovered_snapshot(parent_snapshot, *, url: str, depth: int, title: str = '', tags: str = '', created_by_id: int | None = None)
:canonical: archivebox.crawls.models.Crawl.create_discovered_snapshot

```{autodoc2-docstring} archivebox.crawls.models.Crawl.create_discovered_snapshot
```

````

````{py:method} create_discovered_snapshots(parent_snapshot, records: collections.abc.Iterable[collections.abc.Mapping[str, typing.Any]], *, depth: int, created_by_id: int | None = None) -> list[archivebox.core.models.Snapshot]
:canonical: archivebox.crawls.models.Crawl.create_discovered_snapshots

```{autodoc2-docstring} archivebox.crawls.models.Crawl.create_discovered_snapshots
```

````

````{py:method} install_declared_binaries(binary_names: set[str], machine=None) -> None
:canonical: archivebox.crawls.models.Crawl.install_declared_binaries

```{autodoc2-docstring} archivebox.crawls.models.Crawl.install_declared_binaries
```

````

````{py:method} is_finished() -> bool
:canonical: archivebox.crawls.models.Crawl.is_finished

```{autodoc2-docstring} archivebox.crawls.models.Crawl.is_finished
```

````

````{py:method} can_start() -> bool
:canonical: archivebox.crawls.models.Crawl.can_start

```{autodoc2-docstring} archivebox.crawls.models.Crawl.can_start
```

````

````{py:method} has_finished_snapshots() -> bool
:canonical: archivebox.crawls.models.Crawl.has_finished_snapshots

```{autodoc2-docstring} archivebox.crawls.models.Crawl.has_finished_snapshots
```

````

````{py:method} mark_started() -> bool
:canonical: archivebox.crawls.models.Crawl.mark_started

```{autodoc2-docstring} archivebox.crawls.models.Crawl.mark_started
```

````

````{py:method} seal() -> bool
:canonical: archivebox.crawls.models.Crawl.seal

```{autodoc2-docstring} archivebox.crawls.models.Crawl.seal
```

````

````{py:method} advance_lifecycle() -> bool
:canonical: archivebox.crawls.models.Crawl.advance_lifecycle

```{autodoc2-docstring} archivebox.crawls.models.Crawl.advance_lifecycle
```

````

````{py:method} cleanup_runtime() -> None
:canonical: archivebox.crawls.models.Crawl.cleanup_runtime

```{autodoc2-docstring} archivebox.crawls.models.Crawl.cleanup_runtime
```

````

``````
