# {py:mod}`archivebox.core.takeover_util`

```{py:module} archivebox.core.takeover_util
```

```{autodoc2-docstring} archivebox.core.takeover_util
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`runtime_stack_owner_types <archivebox.core.takeover_util.runtime_stack_owner_types>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_owner_types
    :summary:
    ```
* - {py:obj}`foreground_runner_owner_types <archivebox.core.takeover_util.foreground_runner_owner_types>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.foreground_runner_owner_types
    :summary:
    ```
* - {py:obj}`current_command <archivebox.core.takeover_util.current_command>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.current_command
    :summary:
    ```
* - {py:obj}`live_processes <archivebox.core.takeover_util.live_processes>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.live_processes
    :summary:
    ```
* - {py:obj}`newest_live_process <archivebox.core.takeover_util.newest_live_process>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.newest_live_process
    :summary:
    ```
* - {py:obj}`command_is_newest <archivebox.core.takeover_util.command_is_newest>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.command_is_newest
    :summary:
    ```
* - {py:obj}`runtime_stack_owner <archivebox.core.takeover_util.runtime_stack_owner>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_owner
    :summary:
    ```
* - {py:obj}`command_owns_runtime_stack <archivebox.core.takeover_util.command_owns_runtime_stack>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.command_owns_runtime_stack
    :summary:
    ```
* - {py:obj}`foreground_runner_owner <archivebox.core.takeover_util.foreground_runner_owner>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.foreground_runner_owner
    :summary:
    ```
* - {py:obj}`command_owns_foreground_runner <archivebox.core.takeover_util.command_owns_foreground_runner>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.command_owns_foreground_runner
    :summary:
    ```
* - {py:obj}`runtime_stack_component_label <archivebox.core.takeover_util.runtime_stack_component_label>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_component_label
    :summary:
    ```
* - {py:obj}`ensure_daemon_stack <archivebox.core.takeover_util.ensure_daemon_stack>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.ensure_daemon_stack
    :summary:
    ```
* - {py:obj}`healthy_orchestrator <archivebox.core.takeover_util.healthy_orchestrator>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.healthy_orchestrator
    :summary:
    ```
* - {py:obj}`_runner_sort_key <archivebox.core.takeover_util._runner_sort_key>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util._runner_sort_key
    :summary:
    ```
* - {py:obj}`live_runner_processes <archivebox.core.takeover_util.live_runner_processes>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.live_runner_processes
    :summary:
    ```
* - {py:obj}`enter_single_runner_gate <archivebox.core.takeover_util.enter_single_runner_gate>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.enter_single_runner_gate
    :summary:
    ```
* - {py:obj}`standby_until_leader_needed <archivebox.core.takeover_util.standby_until_leader_needed>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_leader_needed
    :summary:
    ```
* - {py:obj}`standby_until_runtime_stack_needed <archivebox.core.takeover_util.standby_until_runtime_stack_needed>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_runtime_stack_needed
    :summary:
    ```
* - {py:obj}`standby_until_foreground_runner_needed <archivebox.core.takeover_util.standby_until_foreground_runner_needed>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_foreground_runner_needed
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`RUNNER_ACTIVE_WORKER_TYPE <archivebox.core.takeover_util.RUNNER_ACTIVE_WORKER_TYPE>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_ACTIVE_WORKER_TYPE
    :summary:
    ```
* - {py:obj}`RUNNER_WAITING_WORKER_TYPE <archivebox.core.takeover_util.RUNNER_WAITING_WORKER_TYPE>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_WAITING_WORKER_TYPE
    :summary:
    ```
* - {py:obj}`RUNNER_GATE_WORKER_TYPES <archivebox.core.takeover_util.RUNNER_GATE_WORKER_TYPES>`
  - ```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_GATE_WORKER_TYPES
    :summary:
    ```
````

### API

````{py:data} RUNNER_ACTIVE_WORKER_TYPE
:canonical: archivebox.core.takeover_util.RUNNER_ACTIVE_WORKER_TYPE
:value: >
   'worker_runner'

```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_ACTIVE_WORKER_TYPE
```

````

````{py:data} RUNNER_WAITING_WORKER_TYPE
:canonical: archivebox.core.takeover_util.RUNNER_WAITING_WORKER_TYPE
:value: >
   'runner_waiting'

```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_WAITING_WORKER_TYPE
```

````

````{py:data} RUNNER_GATE_WORKER_TYPES
:canonical: archivebox.core.takeover_util.RUNNER_GATE_WORKER_TYPES
:value: >
   ()

```{autodoc2-docstring} archivebox.core.takeover_util.RUNNER_GATE_WORKER_TYPES
```

````

````{py:function} runtime_stack_owner_types()
:canonical: archivebox.core.takeover_util.runtime_stack_owner_types

```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_owner_types
```
````

````{py:function} foreground_runner_owner_types()
:canonical: archivebox.core.takeover_util.foreground_runner_owner_types

```{autodoc2-docstring} archivebox.core.takeover_util.foreground_runner_owner_types
```
````

````{py:function} current_command(process_type: str, *, data_dir: str | pathlib.Path, url: str | None = None)
:canonical: archivebox.core.takeover_util.current_command

```{autodoc2-docstring} archivebox.core.takeover_util.current_command
```
````

````{py:function} live_processes(*, process_type: str, data_dir: str | pathlib.Path, url: str | None = None)
:canonical: archivebox.core.takeover_util.live_processes

```{autodoc2-docstring} archivebox.core.takeover_util.live_processes
```
````

````{py:function} newest_live_process(*, process_type: str, data_dir: str | pathlib.Path, url: str | None = None)
:canonical: archivebox.core.takeover_util.newest_live_process

```{autodoc2-docstring} archivebox.core.takeover_util.newest_live_process
```
````

````{py:function} command_is_newest(command, *, process_type: str, data_dir: str | pathlib.Path, url: str | None = None) -> bool
:canonical: archivebox.core.takeover_util.command_is_newest

```{autodoc2-docstring} archivebox.core.takeover_util.command_is_newest
```
````

````{py:function} runtime_stack_owner(*, data_dir: str | pathlib.Path, exclude_id=None)
:canonical: archivebox.core.takeover_util.runtime_stack_owner

```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_owner
```
````

````{py:function} command_owns_runtime_stack(command, *, data_dir: str | pathlib.Path) -> bool
:canonical: archivebox.core.takeover_util.command_owns_runtime_stack

```{autodoc2-docstring} archivebox.core.takeover_util.command_owns_runtime_stack
```
````

````{py:function} foreground_runner_owner(*, data_dir: str | pathlib.Path, exclude_id=None)
:canonical: archivebox.core.takeover_util.foreground_runner_owner

```{autodoc2-docstring} archivebox.core.takeover_util.foreground_runner_owner
```
````

````{py:function} command_owns_foreground_runner(command, *, data_dir: str | pathlib.Path) -> bool
:canonical: archivebox.core.takeover_util.command_owns_foreground_runner

```{autodoc2-docstring} archivebox.core.takeover_util.command_owns_foreground_runner
```
````

````{py:function} runtime_stack_component_label(*, owner=None, data_dir: str | pathlib.Path) -> str
:canonical: archivebox.core.takeover_util.runtime_stack_component_label

```{autodoc2-docstring} archivebox.core.takeover_util.runtime_stack_component_label
```
````

````{py:function} ensure_daemon_stack(*, reason: str = '')
:canonical: archivebox.core.takeover_util.ensure_daemon_stack

```{autodoc2-docstring} archivebox.core.takeover_util.ensure_daemon_stack
```
````

````{py:function} healthy_orchestrator(*, data_dir: str | pathlib.Path)
:canonical: archivebox.core.takeover_util.healthy_orchestrator

```{autodoc2-docstring} archivebox.core.takeover_util.healthy_orchestrator
```
````

````{py:function} _runner_sort_key(process)
:canonical: archivebox.core.takeover_util._runner_sort_key

```{autodoc2-docstring} archivebox.core.takeover_util._runner_sort_key
```
````

````{py:function} live_runner_processes(*, data_dir: str | pathlib.Path, exclude_id=None)
:canonical: archivebox.core.takeover_util.live_runner_processes

```{autodoc2-docstring} archivebox.core.takeover_util.live_runner_processes
```
````

````{py:function} enter_single_runner_gate(command, *, data_dir: str | pathlib.Path, graceful_timeout: float = 5.0) -> bool
:canonical: archivebox.core.takeover_util.enter_single_runner_gate

```{autodoc2-docstring} archivebox.core.takeover_util.enter_single_runner_gate
```
````

````{py:function} standby_until_leader_needed(command, *, process_type: str, data_dir: str | pathlib.Path, url: str | None = None, interval: float = 2.0) -> None
:canonical: archivebox.core.takeover_util.standby_until_leader_needed

```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_leader_needed
```
````

````{py:function} standby_until_runtime_stack_needed(command, *, data_dir: str | pathlib.Path, interval: float = 2.0) -> dict[str, object]
:canonical: archivebox.core.takeover_util.standby_until_runtime_stack_needed

```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_runtime_stack_needed
```
````

````{py:function} standby_until_foreground_runner_needed(command, *, data_dir: str | pathlib.Path, interval: float = 2.0) -> dict[str, object]
:canonical: archivebox.core.takeover_util.standby_until_foreground_runner_needed

```{autodoc2-docstring} archivebox.core.takeover_util.standby_until_foreground_runner_needed
```
````
