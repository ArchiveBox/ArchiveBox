# {py:mod}`archivebox.workers.supervisord_util`

```{py:module} archivebox.workers.supervisord_util
```

```{autodoc2-docstring} archivebox.workers.supervisord_util
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SupervisordConnectionCache <archivebox.workers.supervisord_util.SupervisordConnectionCache>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.SupervisordConnectionCache
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_shell_join <archivebox.workers.supervisord_util._shell_join>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._shell_join
    :summary:
    ```
* - {py:obj}`_record_supervisord_process <archivebox.workers.supervisord_util._record_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._record_supervisord_process
    :summary:
    ```
* - {py:obj}`_fallback_supervisord_process_from_db <archivebox.workers.supervisord_util._fallback_supervisord_process_from_db>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._fallback_supervisord_process_from_db
    :summary:
    ```
* - {py:obj}`_live_supervisord_processes_from_db <archivebox.workers.supervisord_util._live_supervisord_processes_from_db>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._live_supervisord_processes_from_db
    :summary:
    ```
* - {py:obj}`_stop_older_supervisord_processes <archivebox.workers.supervisord_util._stop_older_supervisord_processes>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._stop_older_supervisord_processes
    :summary:
    ```
* - {py:obj}`RUNSERVER_WORKER <archivebox.workers.supervisord_util.RUNSERVER_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNSERVER_WORKER
    :summary:
    ```
* - {py:obj}`is_port_in_use <archivebox.workers.supervisord_util.is_port_in_use>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.is_port_in_use
    :summary:
    ```
* - {py:obj}`_sonic_worker_bind_target <archivebox.workers.supervisord_util._sonic_worker_bind_target>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._sonic_worker_bind_target
    :summary:
    ```
* - {py:obj}`get_sock_file <archivebox.workers.supervisord_util.get_sock_file>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.get_sock_file
    :summary:
    ```
* - {py:obj}`create_supervisord_config <archivebox.workers.supervisord_util.create_supervisord_config>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.create_supervisord_config
    :summary:
    ```
* - {py:obj}`_worker_environment_value <archivebox.workers.supervisord_util._worker_environment_value>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._worker_environment_value
    :summary:
    ```
* - {py:obj}`_worker_log_base_dir <archivebox.workers.supervisord_util._worker_log_base_dir>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._worker_log_base_dir
    :summary:
    ```
* - {py:obj}`create_worker_config <archivebox.workers.supervisord_util.create_worker_config>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.create_worker_config
    :summary:
    ```
* - {py:obj}`_current_foreground_supervisord_process_id <archivebox.workers.supervisord_util._current_foreground_supervisord_process_id>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._current_foreground_supervisord_process_id
    :summary:
    ```
* - {py:obj}`sync_supervisord_workers <archivebox.workers.supervisord_util.sync_supervisord_workers>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.sync_supervisord_workers
    :summary:
    ```
* - {py:obj}`get_existing_supervisord_process <archivebox.workers.supervisord_util.get_existing_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.get_existing_supervisord_process
    :summary:
    ```
* - {py:obj}`stop_existing_supervisord_process <archivebox.workers.supervisord_util.stop_existing_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_existing_supervisord_process
    :summary:
    ```
* - {py:obj}`stop_own_supervisord_process <archivebox.workers.supervisord_util.stop_own_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_own_supervisord_process
    :summary:
    ```
* - {py:obj}`reap_foreground_supervisord_process <archivebox.workers.supervisord_util.reap_foreground_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.reap_foreground_supervisord_process
    :summary:
    ```
* - {py:obj}`start_new_supervisord_process <archivebox.workers.supervisord_util.start_new_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.start_new_supervisord_process
    :summary:
    ```
* - {py:obj}`wait_for_supervisord_ready <archivebox.workers.supervisord_util.wait_for_supervisord_ready>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.wait_for_supervisord_ready
    :summary:
    ```
* - {py:obj}`get_or_create_supervisord_process <archivebox.workers.supervisord_util.get_or_create_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.get_or_create_supervisord_process
    :summary:
    ```
* - {py:obj}`start_worker <archivebox.workers.supervisord_util.start_worker>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.start_worker
    :summary:
    ```
* - {py:obj}`run_runner_worker <archivebox.workers.supervisord_util.run_runner_worker>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.run_runner_worker
    :summary:
    ```
* - {py:obj}`get_worker <archivebox.workers.supervisord_util.get_worker>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.get_worker
    :summary:
    ```
* - {py:obj}`format_runtime_components <archivebox.workers.supervisord_util.format_runtime_components>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.format_runtime_components
    :summary:
    ```
* - {py:obj}`worker_runtime_component <archivebox.workers.supervisord_util.worker_runtime_component>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.worker_runtime_component
    :summary:
    ```
* - {py:obj}`runtime_components_for_worker_names <archivebox.workers.supervisord_util.runtime_components_for_worker_names>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.runtime_components_for_worker_names
    :summary:
    ```
* - {py:obj}`active_supervisord_runtime_components <archivebox.workers.supervisord_util.active_supervisord_runtime_components>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.active_supervisord_runtime_components
    :summary:
    ```
* - {py:obj}`build_server_worker_plan <archivebox.workers.supervisord_util.build_server_worker_plan>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.build_server_worker_plan
    :summary:
    ```
* - {py:obj}`stop_worker <archivebox.workers.supervisord_util.stop_worker>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_worker
    :summary:
    ```
* - {py:obj}`tail_multiple_worker_logs <archivebox.workers.supervisord_util.tail_multiple_worker_logs>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.tail_multiple_worker_logs
    :summary:
    ```
* - {py:obj}`get_sonic_supervisord_worker_from_plugin <archivebox.workers.supervisord_util.get_sonic_supervisord_worker_from_plugin>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.get_sonic_supervisord_worker_from_plugin
    :summary:
    ```
* - {py:obj}`_proc_cmdline <archivebox.workers.supervisord_util._proc_cmdline>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._proc_cmdline
    :summary:
    ```
* - {py:obj}`_is_sonic_process <archivebox.workers.supervisord_util._is_sonic_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._is_sonic_process
    :summary:
    ```
* - {py:obj}`_is_supervisord_process <archivebox.workers.supervisord_util._is_supervisord_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._is_supervisord_process
    :summary:
    ```
* - {py:obj}`_has_live_archivebox_parent <archivebox.workers.supervisord_util._has_live_archivebox_parent>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._has_live_archivebox_parent
    :summary:
    ```
* - {py:obj}`_terminate_process_tree <archivebox.workers.supervisord_util._terminate_process_tree>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._terminate_process_tree
    :summary:
    ```
* - {py:obj}`_sonic_listeners <archivebox.workers.supervisord_util._sonic_listeners>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._sonic_listeners
    :summary:
    ```
* - {py:obj}`stop_stale_sonic_processes <archivebox.workers.supervisord_util.stop_stale_sonic_processes>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_stale_sonic_processes
    :summary:
    ```
* - {py:obj}`start_server_workers <archivebox.workers.supervisord_util.start_server_workers>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.start_server_workers
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOG_FILE_NAME <archivebox.workers.supervisord_util.LOG_FILE_NAME>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.LOG_FILE_NAME
    :summary:
    ```
* - {py:obj}`CONFIG_FILE_NAME <archivebox.workers.supervisord_util.CONFIG_FILE_NAME>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.CONFIG_FILE_NAME
    :summary:
    ```
* - {py:obj}`PID_FILE_NAME <archivebox.workers.supervisord_util.PID_FILE_NAME>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.PID_FILE_NAME
    :summary:
    ```
* - {py:obj}`WORKERS_DIR_NAME <archivebox.workers.supervisord_util.WORKERS_DIR_NAME>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.WORKERS_DIR_NAME
    :summary:
    ```
* - {py:obj}`_supervisord_proc <archivebox.workers.supervisord_util._supervisord_proc>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._supervisord_proc
    :summary:
    ```
* - {py:obj}`_desired_supervisord_workers <archivebox.workers.supervisord_util._desired_supervisord_workers>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._desired_supervisord_workers
    :summary:
    ```
* - {py:obj}`_ACTIVE_WORKER_STATES <archivebox.workers.supervisord_util._ACTIVE_WORKER_STATES>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._ACTIVE_WORKER_STATES
    :summary:
    ```
* - {py:obj}`_RUNTIME_COMPONENT_ORDER <archivebox.workers.supervisord_util._RUNTIME_COMPONENT_ORDER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util._RUNTIME_COMPONENT_ORDER
    :summary:
    ```
* - {py:obj}`RUNNER_WORKER <archivebox.workers.supervisord_util.RUNNER_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_WORKER
    :summary:
    ```
* - {py:obj}`RUNNER_ONCE_WORKER <archivebox.workers.supervisord_util.RUNNER_ONCE_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_ONCE_WORKER
    :summary:
    ```
* - {py:obj}`RUNNER_WATCH_WORKER <archivebox.workers.supervisord_util.RUNNER_WATCH_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_WATCH_WORKER
    :summary:
    ```
* - {py:obj}`SUPERVISORD_PARENT_WATCHDOG_WORKER <archivebox.workers.supervisord_util.SUPERVISORD_PARENT_WATCHDOG_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.SUPERVISORD_PARENT_WATCHDOG_WORKER
    :summary:
    ```
* - {py:obj}`SERVER_WORKER <archivebox.workers.supervisord_util.SERVER_WORKER>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_util.SERVER_WORKER
    :summary:
    ```
````

### API

````{py:data} LOG_FILE_NAME
:canonical: archivebox.workers.supervisord_util.LOG_FILE_NAME
:value: >
   'supervisord.log'

```{autodoc2-docstring} archivebox.workers.supervisord_util.LOG_FILE_NAME
```

````

````{py:data} CONFIG_FILE_NAME
:canonical: archivebox.workers.supervisord_util.CONFIG_FILE_NAME
:value: >
   'supervisord.conf'

```{autodoc2-docstring} archivebox.workers.supervisord_util.CONFIG_FILE_NAME
```

````

````{py:data} PID_FILE_NAME
:canonical: archivebox.workers.supervisord_util.PID_FILE_NAME
:value: >
   'supervisord.pid'

```{autodoc2-docstring} archivebox.workers.supervisord_util.PID_FILE_NAME
```

````

````{py:data} WORKERS_DIR_NAME
:canonical: archivebox.workers.supervisord_util.WORKERS_DIR_NAME
:value: >
   'workers'

```{autodoc2-docstring} archivebox.workers.supervisord_util.WORKERS_DIR_NAME
```

````

````{py:data} _supervisord_proc
:canonical: archivebox.workers.supervisord_util._supervisord_proc
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util._supervisord_proc
```

````

````{py:data} _desired_supervisord_workers
:canonical: archivebox.workers.supervisord_util._desired_supervisord_workers
:type: dict[str, dict[str, str]]
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util._desired_supervisord_workers
```

````

````{py:data} _ACTIVE_WORKER_STATES
:canonical: archivebox.workers.supervisord_util._ACTIVE_WORKER_STATES
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util._ACTIVE_WORKER_STATES
```

````

````{py:data} _RUNTIME_COMPONENT_ORDER
:canonical: archivebox.workers.supervisord_util._RUNTIME_COMPONENT_ORDER
:value: >
   ('orchestrator', 'server', 'sonic')

```{autodoc2-docstring} archivebox.workers.supervisord_util._RUNTIME_COMPONENT_ORDER
```

````

````{py:function} _shell_join(args: list[str]) -> str
:canonical: archivebox.workers.supervisord_util._shell_join

```{autodoc2-docstring} archivebox.workers.supervisord_util._shell_join
```
````

````{py:function} _record_supervisord_process(proc: subprocess.Popen, config_file: pathlib.Path) -> None
:canonical: archivebox.workers.supervisord_util._record_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util._record_supervisord_process
```
````

````{py:function} _fallback_supervisord_process_from_db()
:canonical: archivebox.workers.supervisord_util._fallback_supervisord_process_from_db

```{autodoc2-docstring} archivebox.workers.supervisord_util._fallback_supervisord_process_from_db
```
````

````{py:function} _live_supervisord_processes_from_db()
:canonical: archivebox.workers.supervisord_util._live_supervisord_processes_from_db

```{autodoc2-docstring} archivebox.workers.supervisord_util._live_supervisord_processes_from_db
```
````

````{py:function} _stop_older_supervisord_processes(*, current_pid: int, current_started_at: float, timeout: float) -> None
:canonical: archivebox.workers.supervisord_util._stop_older_supervisord_processes

```{autodoc2-docstring} archivebox.workers.supervisord_util._stop_older_supervisord_processes
```
````

````{py:data} RUNNER_WORKER
:canonical: archivebox.workers.supervisord_util.RUNNER_WORKER
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_WORKER
```

````

````{py:data} RUNNER_ONCE_WORKER
:canonical: archivebox.workers.supervisord_util.RUNNER_ONCE_WORKER
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_ONCE_WORKER
```

````

````{py:data} RUNNER_WATCH_WORKER
:canonical: archivebox.workers.supervisord_util.RUNNER_WATCH_WORKER
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNNER_WATCH_WORKER
```

````

````{py:data} SUPERVISORD_PARENT_WATCHDOG_WORKER
:canonical: archivebox.workers.supervisord_util.SUPERVISORD_PARENT_WATCHDOG_WORKER
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util.SUPERVISORD_PARENT_WATCHDOG_WORKER
```

````

````{py:data} SERVER_WORKER
:canonical: archivebox.workers.supervisord_util.SERVER_WORKER
:value: >
   None

```{autodoc2-docstring} archivebox.workers.supervisord_util.SERVER_WORKER
```

````

````{py:function} RUNSERVER_WORKER(host: str, port: str, *, reload: bool, nothreading: bool = False)
:canonical: archivebox.workers.supervisord_util.RUNSERVER_WORKER

```{autodoc2-docstring} archivebox.workers.supervisord_util.RUNSERVER_WORKER
```
````

````{py:function} is_port_in_use(host: str, port: int) -> bool
:canonical: archivebox.workers.supervisord_util.is_port_in_use

```{autodoc2-docstring} archivebox.workers.supervisord_util.is_port_in_use
```
````

````{py:function} _sonic_worker_bind_target(worker: dict[str, str]) -> tuple[str, int] | None
:canonical: archivebox.workers.supervisord_util._sonic_worker_bind_target

```{autodoc2-docstring} archivebox.workers.supervisord_util._sonic_worker_bind_target
```
````

````{py:function} get_sock_file()
:canonical: archivebox.workers.supervisord_util.get_sock_file

```{autodoc2-docstring} archivebox.workers.supervisord_util.get_sock_file
```
````

````{py:function} create_supervisord_config()
:canonical: archivebox.workers.supervisord_util.create_supervisord_config

```{autodoc2-docstring} archivebox.workers.supervisord_util.create_supervisord_config
```
````

````{py:function} _worker_environment_value(daemon: dict[str, str], key: str) -> str | None
:canonical: archivebox.workers.supervisord_util._worker_environment_value

```{autodoc2-docstring} archivebox.workers.supervisord_util._worker_environment_value
```
````

````{py:function} _worker_log_base_dir(daemon: dict[str, str]) -> pathlib.Path
:canonical: archivebox.workers.supervisord_util._worker_log_base_dir

```{autodoc2-docstring} archivebox.workers.supervisord_util._worker_log_base_dir
```
````

````{py:function} create_worker_config(daemon)
:canonical: archivebox.workers.supervisord_util.create_worker_config

```{autodoc2-docstring} archivebox.workers.supervisord_util.create_worker_config
```
````

````{py:function} _current_foreground_supervisord_process_id()
:canonical: archivebox.workers.supervisord_util._current_foreground_supervisord_process_id

```{autodoc2-docstring} archivebox.workers.supervisord_util._current_foreground_supervisord_process_id
```
````

````{py:function} sync_supervisord_workers(supervisor, workers: list[tuple[dict[str, str], bool]], *, prune: bool = True)
:canonical: archivebox.workers.supervisord_util.sync_supervisord_workers

```{autodoc2-docstring} archivebox.workers.supervisord_util.sync_supervisord_workers
```
````

````{py:function} get_existing_supervisord_process(*, quiet: bool = False)
:canonical: archivebox.workers.supervisord_util.get_existing_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.get_existing_supervisord_process
```
````

`````{py:class} SupervisordConnectionCache(*, quiet: bool = False)
:canonical: archivebox.workers.supervisord_util.SupervisordConnectionCache

```{autodoc2-docstring} archivebox.workers.supervisord_util.SupervisordConnectionCache
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.workers.supervisord_util.SupervisordConnectionCache.__init__
```

````{py:method} clear() -> None
:canonical: archivebox.workers.supervisord_util.SupervisordConnectionCache.clear

```{autodoc2-docstring} archivebox.workers.supervisord_util.SupervisordConnectionCache.clear
```

````

````{py:method} get()
:canonical: archivebox.workers.supervisord_util.SupervisordConnectionCache.get

```{autodoc2-docstring} archivebox.workers.supervisord_util.SupervisordConnectionCache.get
```

````

`````

````{py:function} stop_existing_supervisord_process()
:canonical: archivebox.workers.supervisord_util.stop_existing_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_existing_supervisord_process
```
````

````{py:function} stop_own_supervisord_process(*, record_exit: bool = True)
:canonical: archivebox.workers.supervisord_util.stop_own_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_own_supervisord_process
```
````

````{py:function} reap_foreground_supervisord_process() -> None
:canonical: archivebox.workers.supervisord_util.reap_foreground_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.reap_foreground_supervisord_process
```
````

````{py:function} start_new_supervisord_process(daemonize=False)
:canonical: archivebox.workers.supervisord_util.start_new_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.start_new_supervisord_process
```
````

````{py:function} wait_for_supervisord_ready(max_wait_sec: float = 5.0, interval_sec: float = 0.1, *, quiet: bool = False)
:canonical: archivebox.workers.supervisord_util.wait_for_supervisord_ready

```{autodoc2-docstring} archivebox.workers.supervisord_util.wait_for_supervisord_ready
```
````

````{py:function} get_or_create_supervisord_process(daemonize=False)
:canonical: archivebox.workers.supervisord_util.get_or_create_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util.get_or_create_supervisord_process
```
````

````{py:function} start_worker(supervisor, daemon, lazy=False)
:canonical: archivebox.workers.supervisord_util.start_worker

```{autodoc2-docstring} archivebox.workers.supervisord_util.start_worker
```
````

````{py:function} run_runner_worker(args: list[str], *, name: str = 'worker_runner_once', interactive_interrupts: bool = False, keep_running=None) -> int
:canonical: archivebox.workers.supervisord_util.run_runner_worker

```{autodoc2-docstring} archivebox.workers.supervisord_util.run_runner_worker
```
````

````{py:function} get_worker(supervisor, daemon_name)
:canonical: archivebox.workers.supervisord_util.get_worker

```{autodoc2-docstring} archivebox.workers.supervisord_util.get_worker
```
````

````{py:function} format_runtime_components(components: list[str] | tuple[str, ...]) -> str
:canonical: archivebox.workers.supervisord_util.format_runtime_components

```{autodoc2-docstring} archivebox.workers.supervisord_util.format_runtime_components
```
````

````{py:function} worker_runtime_component(worker_name: str, *, config=None) -> str | None
:canonical: archivebox.workers.supervisord_util.worker_runtime_component

```{autodoc2-docstring} archivebox.workers.supervisord_util.worker_runtime_component
```
````

````{py:function} runtime_components_for_worker_names(worker_names: set[str] | list[str] | tuple[str, ...], *, config=None) -> list[str]
:canonical: archivebox.workers.supervisord_util.runtime_components_for_worker_names

```{autodoc2-docstring} archivebox.workers.supervisord_util.runtime_components_for_worker_names
```
````

````{py:function} active_supervisord_runtime_components(*, config=None, supervisor=None) -> list[str]
:canonical: archivebox.workers.supervisord_util.active_supervisord_runtime_components

```{autodoc2-docstring} archivebox.workers.supervisord_util.active_supervisord_runtime_components
```
````

````{py:function} build_server_worker_plan(*, config, host: str, port: str, debug: bool, reload: bool, nothreading: bool, supervisor=None)
:canonical: archivebox.workers.supervisord_util.build_server_worker_plan

```{autodoc2-docstring} archivebox.workers.supervisord_util.build_server_worker_plan
```
````

````{py:function} stop_worker(supervisor, daemon_name)
:canonical: archivebox.workers.supervisord_util.stop_worker

```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_worker
```
````

````{py:function} tail_multiple_worker_logs(log_files: list[str], follow=True, proc=None, keep_running=None)
:canonical: archivebox.workers.supervisord_util.tail_multiple_worker_logs

```{autodoc2-docstring} archivebox.workers.supervisord_util.tail_multiple_worker_logs
```
````

````{py:function} get_sonic_supervisord_worker_from_plugin(config) -> dict[str, str] | None
:canonical: archivebox.workers.supervisord_util.get_sonic_supervisord_worker_from_plugin

```{autodoc2-docstring} archivebox.workers.supervisord_util.get_sonic_supervisord_worker_from_plugin
```
````

````{py:function} _proc_cmdline(proc: psutil.Process) -> list[str]
:canonical: archivebox.workers.supervisord_util._proc_cmdline

```{autodoc2-docstring} archivebox.workers.supervisord_util._proc_cmdline
```
````

````{py:function} _is_sonic_process(proc: psutil.Process) -> bool
:canonical: archivebox.workers.supervisord_util._is_sonic_process

```{autodoc2-docstring} archivebox.workers.supervisord_util._is_sonic_process
```
````

````{py:function} _is_supervisord_process(proc: psutil.Process | None) -> bool
:canonical: archivebox.workers.supervisord_util._is_supervisord_process

```{autodoc2-docstring} archivebox.workers.supervisord_util._is_supervisord_process
```
````

````{py:function} _has_live_archivebox_parent(proc: psutil.Process | None) -> bool
:canonical: archivebox.workers.supervisord_util._has_live_archivebox_parent

```{autodoc2-docstring} archivebox.workers.supervisord_util._has_live_archivebox_parent
```
````

````{py:function} _terminate_process_tree(root: psutil.Process, *, timeout: float = 2.0) -> None
:canonical: archivebox.workers.supervisord_util._terminate_process_tree

```{autodoc2-docstring} archivebox.workers.supervisord_util._terminate_process_tree
```
````

````{py:function} _sonic_listeners(host: str, port: int) -> list[psutil.Process]
:canonical: archivebox.workers.supervisord_util._sonic_listeners

```{autodoc2-docstring} archivebox.workers.supervisord_util._sonic_listeners
```
````

````{py:function} stop_stale_sonic_processes(sonic_worker: dict[str, str], *, supervisor_pid: int | None, host: str | None = None, port: int | None = None) -> None
:canonical: archivebox.workers.supervisord_util.stop_stale_sonic_processes

```{autodoc2-docstring} archivebox.workers.supervisord_util.stop_stale_sonic_processes
```
````

````{py:function} start_server_workers(host='0.0.0.0', port='8000', daemonize=False, debug=False, reload=False, nothreading=False, keep_running=None, should_stop_supervisord=None, resumed_from_pid=None)
:canonical: archivebox.workers.supervisord_util.start_server_workers

```{autodoc2-docstring} archivebox.workers.supervisord_util.start_server_workers
```
````
