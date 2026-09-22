# {py:mod}`archivebox.services.runner`

```{py:module} archivebox.services.runner
```

```{autodoc2-docstring} archivebox.services.runner
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CrawlRunner <archivebox.services.runner.CrawlRunner>`
  - ```{autodoc2-docstring} archivebox.services.runner.CrawlRunner
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_bus_name <archivebox.services.runner._bus_name>`
  - ```{autodoc2-docstring} archivebox.services.runner._bus_name
    :summary:
    ```
* - {py:obj}`_runner_short_id <archivebox.services.runner._runner_short_id>`
  - ```{autodoc2-docstring} archivebox.services.runner._runner_short_id
    :summary:
    ```
* - {py:obj}`_runner_label <archivebox.services.runner._runner_label>`
  - ```{autodoc2-docstring} archivebox.services.runner._runner_label
    :summary:
    ```
* - {py:obj}`_runner_console_line <archivebox.services.runner._runner_console_line>`
  - ```{autodoc2-docstring} archivebox.services.runner._runner_console_line
    :summary:
    ```
* - {py:obj}`_count_selected_hooks <archivebox.services.runner._count_selected_hooks>`
  - ```{autodoc2-docstring} archivebox.services.runner._count_selected_hooks
    :summary:
    ```
* - {py:obj}`_is_nonfatal_setup_hook <archivebox.services.runner._is_nonfatal_setup_hook>`
  - ```{autodoc2-docstring} archivebox.services.runner._is_nonfatal_setup_hook
    :summary:
    ```
* - {py:obj}`_runner_task_context <archivebox.services.runner._runner_task_context>`
  - ```{autodoc2-docstring} archivebox.services.runner._runner_task_context
    :summary:
    ```
* - {py:obj}`_is_external_task_cancelled <archivebox.services.runner._is_external_task_cancelled>`
  - ```{autodoc2-docstring} archivebox.services.runner._is_external_task_cancelled
    :summary:
    ```
* - {py:obj}`_run_event_now <archivebox.services.runner._run_event_now>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_event_now
    :summary:
    ```
* - {py:obj}`ensure_background_runner <archivebox.services.runner.ensure_background_runner>`
  - ```{autodoc2-docstring} archivebox.services.runner.ensure_background_runner
    :summary:
    ```
* - {py:obj}`run_crawl <archivebox.services.runner.run_crawl>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_crawl
    :summary:
    ```
* - {py:obj}`_run_crawl_locked <archivebox.services.runner._run_crawl_locked>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_crawl_locked
    :summary:
    ```
* - {py:obj}`_run_binary <archivebox.services.runner._run_binary>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_binary
    :summary:
    ```
* - {py:obj}`run_binary <archivebox.services.runner.run_binary>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_binary
    :summary:
    ```
* - {py:obj}`queued_plugins_and_hooks_for_snapshot <archivebox.services.runner.queued_plugins_and_hooks_for_snapshot>`
  - ```{autodoc2-docstring} archivebox.services.runner.queued_plugins_and_hooks_for_snapshot
    :summary:
    ```
* - {py:obj}`queued_plugins_for_snapshot <archivebox.services.runner.queued_plugins_for_snapshot>`
  - ```{autodoc2-docstring} archivebox.services.runner.queued_plugins_for_snapshot
    :summary:
    ```
* - {py:obj}`config_overrides_for_queued_plugins <archivebox.services.runner.config_overrides_for_queued_plugins>`
  - ```{autodoc2-docstring} archivebox.services.runner.config_overrides_for_queued_plugins
    :summary:
    ```
* - {py:obj}`fail_unavailable_queued_hooks <archivebox.services.runner.fail_unavailable_queued_hooks>`
  - ```{autodoc2-docstring} archivebox.services.runner.fail_unavailable_queued_hooks
    :summary:
    ```
* - {py:obj}`skip_disabled_queued_plugins <archivebox.services.runner.skip_disabled_queued_plugins>`
  - ```{autodoc2-docstring} archivebox.services.runner.skip_disabled_queued_plugins
    :summary:
    ```
* - {py:obj}`include_background_prerequisite_hooks <archivebox.services.runner.include_background_prerequisite_hooks>`
  - ```{autodoc2-docstring} archivebox.services.runner.include_background_prerequisite_hooks
    :summary:
    ```
* - {py:obj}`snapshot_hooks_for_pending_archiveresults <archivebox.services.runner.snapshot_hooks_for_pending_archiveresults>`
  - ```{autodoc2-docstring} archivebox.services.runner.snapshot_hooks_for_pending_archiveresults
    :summary:
    ```
* - {py:obj}`run_snapshot_maintenance <archivebox.services.runner.run_snapshot_maintenance>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_snapshot_maintenance
    :summary:
    ```
* - {py:obj}`run_due_crawl <archivebox.services.runner.run_due_crawl>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_due_crawl
    :summary:
    ```
* - {py:obj}`_run_due_crawl_locked <archivebox.services.runner._run_due_crawl_locked>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_crawl_locked
    :summary:
    ```
* - {py:obj}`run_due_snapshot <archivebox.services.runner.run_due_snapshot>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_due_snapshot
    :summary:
    ```
* - {py:obj}`_run_due_snapshot_locked <archivebox.services.runner._run_due_snapshot_locked>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_locked
    :summary:
    ```
* - {py:obj}`run_due_binary <archivebox.services.runner.run_due_binary>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_due_binary
    :summary:
    ```
* - {py:obj}`_run_install <archivebox.services.runner._run_install>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_install
    :summary:
    ```
* - {py:obj}`run_install <archivebox.services.runner.run_install>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_install
    :summary:
    ```
* - {py:obj}`_first_due_id <archivebox.services.runner._first_due_id>`
  - ```{autodoc2-docstring} archivebox.services.runner._first_due_id
    :summary:
    ```
* - {py:obj}`_run_due_crawl_status <archivebox.services.runner._run_due_crawl_status>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_crawl_status
    :summary:
    ```
* - {py:obj}`_run_due_snapshot_query <archivebox.services.runner._run_due_snapshot_query>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_query
    :summary:
    ```
* - {py:obj}`_run_due_snapshot_id <archivebox.services.runner._run_due_snapshot_id>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_id
    :summary:
    ```
* - {py:obj}`_run_due_queued_plugin_result <archivebox.services.runner._run_due_queued_plugin_result>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_queued_plugin_result
    :summary:
    ```
* - {py:obj}`_run_due_binary <archivebox.services.runner._run_due_binary>`
  - ```{autodoc2-docstring} archivebox.services.runner._run_due_binary
    :summary:
    ```
* - {py:obj}`_fast_forward_same_path_snapshot_fs_versions <archivebox.services.runner._fast_forward_same_path_snapshot_fs_versions>`
  - ```{autodoc2-docstring} archivebox.services.runner._fast_forward_same_path_snapshot_fs_versions
    :summary:
    ```
* - {py:obj}`run_pending_crawls <archivebox.services.runner.run_pending_crawls>`
  - ```{autodoc2-docstring} archivebox.services.runner.run_pending_crawls
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`QUEUED_PLUGIN_RESULT_BATCH_SIZE <archivebox.services.runner.QUEUED_PLUGIN_RESULT_BATCH_SIZE>`
  - ```{autodoc2-docstring} archivebox.services.runner.QUEUED_PLUGIN_RESULT_BATCH_SIZE
    :summary:
    ```
````

### API

````{py:data} QUEUED_PLUGIN_RESULT_BATCH_SIZE
:canonical: archivebox.services.runner.QUEUED_PLUGIN_RESULT_BATCH_SIZE
:value: >
   100

```{autodoc2-docstring} archivebox.services.runner.QUEUED_PLUGIN_RESULT_BATCH_SIZE
```

````

````{py:function} _bus_name(prefix: str, identifier: str) -> str
:canonical: archivebox.services.runner._bus_name

```{autodoc2-docstring} archivebox.services.runner._bus_name
```
````

````{py:function} _runner_short_id(identifier) -> str
:canonical: archivebox.services.runner._runner_short_id

```{autodoc2-docstring} archivebox.services.runner._runner_short_id
```
````

````{py:function} _runner_label(value: str, *, reserve: int) -> str
:canonical: archivebox.services.runner._runner_label

```{autodoc2-docstring} archivebox.services.runner._runner_label
```
````

````{py:function} _runner_console_line(*, crawl=None, crawl_id=None, snapshot=None, status: str = 'STARTED') -> None
:canonical: archivebox.services.runner._runner_console_line

```{autodoc2-docstring} archivebox.services.runner._runner_console_line
```
````

````{py:function} _count_selected_hooks(plugins: dict[str, abx_dl.models.Plugin], selected_plugins: list[str] | None) -> int
:canonical: archivebox.services.runner._count_selected_hooks

```{autodoc2-docstring} archivebox.services.runner._count_selected_hooks
```
````

````{py:function} _is_nonfatal_setup_hook(plugin_name: str, hook_name: str) -> bool
:canonical: archivebox.services.runner._is_nonfatal_setup_hook

```{autodoc2-docstring} archivebox.services.runner._is_nonfatal_setup_hook
```
````

````{py:function} _runner_task_context() -> contextvars.Context
:canonical: archivebox.services.runner._runner_task_context

```{autodoc2-docstring} archivebox.services.runner._runner_task_context
```
````

````{py:function} _is_external_task_cancelled(error: asyncio.CancelledError) -> bool
:canonical: archivebox.services.runner._is_external_task_cancelled

```{autodoc2-docstring} archivebox.services.runner._is_external_task_cancelled
```
````

````{py:function} _run_event_now(event, timeout: float | None = None)
:canonical: archivebox.services.runner._run_event_now
:async:

```{autodoc2-docstring} archivebox.services.runner._run_event_now
```
````

````{py:function} ensure_background_runner() -> bool
:canonical: archivebox.services.runner.ensure_background_runner

```{autodoc2-docstring} archivebox.services.runner.ensure_background_runner
```
````

`````{py:class} CrawlRunner(crawl, *, snapshot_ids: list[str] | None = None, selected_plugins: list[str] | None = None, process_discovered_snapshots_inline: bool = True, show_progress: bool = True, interactive_interrupts: bool = False, config_overrides: dict[str, typing.Any] | None = None, selected_plugins_are_explicit: bool = True)
:canonical: archivebox.services.runner.CrawlRunner

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.__init__
```

````{py:method} _request_abort_from_signal(_sig: signal.Signals) -> None
:canonical: archivebox.services.runner.CrawlRunner._request_abort_from_signal

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner._request_abort_from_signal
```

````

````{py:method} crawl_is_cancelled() -> bool
:canonical: archivebox.services.runner.CrawlRunner.crawl_is_cancelled
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.crawl_is_cancelled
```

````

````{py:method} crawl_is_paused() -> bool
:canonical: archivebox.services.runner.CrawlRunner.crawl_is_paused
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.crawl_is_paused
```

````

````{py:method} watch_for_cancelled_crawl(parent_event: abxbus.BaseEvent, *, poll_interval: float = 1.0) -> None
:canonical: archivebox.services.runner.CrawlRunner.watch_for_cancelled_crawl
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.watch_for_cancelled_crawl
```

````

````{py:property} allow_maintenance_on_inactive_crawl
:canonical: archivebox.services.runner.CrawlRunner.allow_maintenance_on_inactive_crawl
:type: bool

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.allow_maintenance_on_inactive_crawl
```

````

````{py:method} run() -> None
:canonical: archivebox.services.runner.CrawlRunner.run
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.run
```

````

````{py:method} enqueue_snapshot(snapshot_id: str, crawl_start_event: abx_dl.events.CrawlStartEvent | None = None) -> None
:canonical: archivebox.services.runner.CrawlRunner.enqueue_snapshot
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.enqueue_snapshot
```

````

````{py:method} stop_snapshot_tasks() -> None
:canonical: archivebox.services.runner.CrawlRunner.stop_snapshot_tasks
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.stop_snapshot_tasks
```

````

````{py:method} wait_for_snapshot_tasks() -> None
:canonical: archivebox.services.runner.CrawlRunner.wait_for_snapshot_tasks
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.wait_for_snapshot_tasks
```

````

````{py:method} heartbeat_active_leases() -> None
:canonical: archivebox.services.runner.CrawlRunner.heartbeat_active_leases
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.heartbeat_active_leases
```

````

````{py:method} drain_snapshot_tasks() -> None
:canonical: archivebox.services.runner.CrawlRunner.drain_snapshot_tasks
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.drain_snapshot_tasks
```

````

````{py:method} enqueue_pending_snapshots_from_projection() -> None
:canonical: archivebox.services.runner.CrawlRunner.enqueue_pending_snapshots_from_projection
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.enqueue_pending_snapshots_from_projection
```

````

````{py:method} load_run_state() -> list[str]
:canonical: archivebox.services.runner.CrawlRunner.load_run_state

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.load_run_state
```

````

````{py:method} create_initial_snapshots() -> list
:canonical: archivebox.services.runner.CrawlRunner.create_initial_snapshots

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.create_initial_snapshots
```

````

````{py:method} finalize_run_state() -> None
:canonical: archivebox.services.runner.CrawlRunner.finalize_run_state

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.finalize_run_state
```

````

````{py:method} _create_live_ui() -> abx_dl.cli.LiveBusUI | None
:canonical: archivebox.services.runner.CrawlRunner._create_live_ui

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner._create_live_ui
```

````

````{py:method} load_snapshot_payload(snapshot_id: str) -> dict[str, typing.Any]
:canonical: archivebox.services.runner.CrawlRunner.load_snapshot_payload

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.load_snapshot_payload
```

````

````{py:method} enqueue_discovered_snapshots_from_outputs(snapshot_payload: dict[str, typing.Any]) -> None
:canonical: archivebox.services.runner.CrawlRunner.enqueue_discovered_snapshots_from_outputs
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.enqueue_discovered_snapshots_from_outputs
```

````

````{py:method} run_crawl(root_snapshot_id: str, snapshot_ids: list[str]) -> None
:canonical: archivebox.services.runner.CrawlRunner.run_crawl
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.run_crawl
```

````

````{py:method} run_snapshot(snapshot_id: str, crawl_start_event: abx_dl.events.CrawlStartEvent | None = None) -> None
:canonical: archivebox.services.runner.CrawlRunner.run_snapshot
:async:

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.run_snapshot
```

````

````{py:method} seal_snapshot_due_to_limit(snapshot_id: str) -> None
:canonical: archivebox.services.runner.CrawlRunner.seal_snapshot_due_to_limit

```{autodoc2-docstring} archivebox.services.runner.CrawlRunner.seal_snapshot_due_to_limit
```

````

`````

````{py:function} run_crawl(crawl_id: str, *, snapshot_ids: list[str] | None = None, selected_plugins: list[str] | None = None, process_discovered_snapshots_inline: bool = True, show_progress: bool = True, interactive_interrupts: bool = False, config_overrides: dict[str, typing.Any] | None = None, selected_plugins_are_explicit: bool = True) -> None
:canonical: archivebox.services.runner.run_crawl

```{autodoc2-docstring} archivebox.services.runner.run_crawl
```
````

````{py:function} _run_crawl_locked(crawl_id: str, *, snapshot_ids: list[str] | None = None, selected_plugins: list[str] | None = None, process_discovered_snapshots_inline: bool = True, show_progress: bool = True, interactive_interrupts: bool = False, config_overrides: dict[str, typing.Any] | None = None, selected_plugins_are_explicit: bool = True) -> None
:canonical: archivebox.services.runner._run_crawl_locked

```{autodoc2-docstring} archivebox.services.runner._run_crawl_locked
```
````

````{py:function} _run_binary(binary_id: str) -> None
:canonical: archivebox.services.runner._run_binary
:async:

```{autodoc2-docstring} archivebox.services.runner._run_binary
```
````

````{py:function} run_binary(binary_id: str) -> None
:canonical: archivebox.services.runner.run_binary

```{autodoc2-docstring} archivebox.services.runner.run_binary
```
````

````{py:function} queued_plugins_and_hooks_for_snapshot(snapshot_id: str) -> tuple[list[str] | None, dict[str, set[str] | None] | None]
:canonical: archivebox.services.runner.queued_plugins_and_hooks_for_snapshot

```{autodoc2-docstring} archivebox.services.runner.queued_plugins_and_hooks_for_snapshot
```
````

````{py:function} queued_plugins_for_snapshot(snapshot_id: str) -> list[str] | None
:canonical: archivebox.services.runner.queued_plugins_for_snapshot

```{autodoc2-docstring} archivebox.services.runner.queued_plugins_for_snapshot
```
````

````{py:function} config_overrides_for_queued_plugins(selected_plugins: list[str], **overrides: typing.Any) -> dict[str, typing.Any]
:canonical: archivebox.services.runner.config_overrides_for_queued_plugins

```{autodoc2-docstring} archivebox.services.runner.config_overrides_for_queued_plugins
```
````

````{py:function} fail_unavailable_queued_hooks(snapshot_id: str, selected_hooks_by_plugin: dict[str, set[str] | None], plugins: dict[str, abx_dl.models.Plugin]) -> None
:canonical: archivebox.services.runner.fail_unavailable_queued_hooks

```{autodoc2-docstring} archivebox.services.runner.fail_unavailable_queued_hooks
```
````

````{py:function} skip_disabled_queued_plugins(snapshot_id: str, plugin_names: list[str]) -> None
:canonical: archivebox.services.runner.skip_disabled_queued_plugins

```{autodoc2-docstring} archivebox.services.runner.skip_disabled_queued_plugins
```
````

````{py:function} include_background_prerequisite_hooks(selected_hooks_by_plugin: dict[str, set[str] | None], plugins: dict[str, abx_dl.models.Plugin]) -> dict[str, set[str] | None]
:canonical: archivebox.services.runner.include_background_prerequisite_hooks

```{autodoc2-docstring} archivebox.services.runner.include_background_prerequisite_hooks
```
````

````{py:function} snapshot_hooks_for_pending_archiveresults(snapshot) -> list[tuple[str, str]]
:canonical: archivebox.services.runner.snapshot_hooks_for_pending_archiveresults

```{autodoc2-docstring} archivebox.services.runner.snapshot_hooks_for_pending_archiveresults
```
````

````{py:function} run_snapshot_maintenance(snapshot_id: str, *, output_dir: pathlib.Path | None = None) -> bool
:canonical: archivebox.services.runner.run_snapshot_maintenance

```{autodoc2-docstring} archivebox.services.runner.run_snapshot_maintenance
```
````

````{py:function} run_due_crawl(crawl, *, lock_seconds: int, interactive_interrupts: bool = False) -> bool
:canonical: archivebox.services.runner.run_due_crawl

```{autodoc2-docstring} archivebox.services.runner.run_due_crawl
```
````

````{py:function} _run_due_crawl_locked(crawl, *, lock_seconds: int, interactive_interrupts: bool = False) -> bool
:canonical: archivebox.services.runner._run_due_crawl_locked

```{autodoc2-docstring} archivebox.services.runner._run_due_crawl_locked
```
````

````{py:function} run_due_snapshot(snapshot, *, lock_seconds: int, interactive_interrupts: bool = False, runtime_config=None) -> bool
:canonical: archivebox.services.runner.run_due_snapshot

```{autodoc2-docstring} archivebox.services.runner.run_due_snapshot
```
````

````{py:function} _run_due_snapshot_locked(snapshot, *, lock_seconds: int, interactive_interrupts: bool = False, runtime_config=None) -> bool
:canonical: archivebox.services.runner._run_due_snapshot_locked

```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_locked
```
````

````{py:function} run_due_binary(binary, *, lock_seconds: int) -> bool
:canonical: archivebox.services.runner.run_due_binary

```{autodoc2-docstring} archivebox.services.runner.run_due_binary
```
````

````{py:function} _run_install(plugin_names: list[str] | None = None) -> None
:canonical: archivebox.services.runner._run_install
:async:

```{autodoc2-docstring} archivebox.services.runner._run_install
```
````

````{py:function} run_install(*, plugin_names: list[str] | None = None) -> None
:canonical: archivebox.services.runner.run_install

```{autodoc2-docstring} archivebox.services.runner.run_install
```
````

````{py:function} _first_due_id(queryset)
:canonical: archivebox.services.runner._first_due_id

```{autodoc2-docstring} archivebox.services.runner._first_due_id
```
````

````{py:function} _run_due_crawl_status(status: str, *, crawl_id: str | None, lock_seconds: int, interactive_interrupts: bool) -> bool
:canonical: archivebox.services.runner._run_due_crawl_status

```{autodoc2-docstring} archivebox.services.runner._run_due_crawl_status
```
````

````{py:function} _run_due_snapshot_query(queryset, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool
:canonical: archivebox.services.runner._run_due_snapshot_query

```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_query
```
````

````{py:function} _run_due_snapshot_id(snapshot_id, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool
:canonical: archivebox.services.runner._run_due_snapshot_id

```{autodoc2-docstring} archivebox.services.runner._run_due_snapshot_id
```
````

````{py:function} _run_due_queued_plugin_result(plugin_names: frozenset[str], *, crawl_id: str | None, lock_seconds: int, interactive_interrupts: bool, runtime_config, batch_size: int = QUEUED_PLUGIN_RESULT_BATCH_SIZE) -> bool
:canonical: archivebox.services.runner._run_due_queued_plugin_result

```{autodoc2-docstring} archivebox.services.runner._run_due_queued_plugin_result
```
````

````{py:function} _run_due_binary() -> bool
:canonical: archivebox.services.runner._run_due_binary

```{autodoc2-docstring} archivebox.services.runner._run_due_binary
```
````

````{py:function} _fast_forward_same_path_snapshot_fs_versions(batch_size: int = 10000) -> bool
:canonical: archivebox.services.runner._fast_forward_same_path_snapshot_fs_versions

```{autodoc2-docstring} archivebox.services.runner._fast_forward_same_path_snapshot_fs_versions
```
````

````{py:function} run_pending_crawls(*, daemon: bool = False, crawl_id: str | None = None, maintenance_only: bool = False, interactive_interrupts: bool = False, maintenance_batch_size: int = QUEUED_PLUGIN_RESULT_BATCH_SIZE) -> int
:canonical: archivebox.services.runner.run_pending_crawls

```{autodoc2-docstring} archivebox.services.runner.run_pending_crawls
```
````
