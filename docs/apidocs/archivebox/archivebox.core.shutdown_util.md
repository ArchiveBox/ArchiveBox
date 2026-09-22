# {py:mod}`archivebox.core.shutdown_util`

```{py:module} archivebox.core.shutdown_util
```

```{autodoc2-docstring} archivebox.core.shutdown_util
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ShutdownSignalState <archivebox.core.shutdown_util.ShutdownSignalState>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.ShutdownSignalState
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`raise_if_shutdown_requested <archivebox.core.shutdown_util.raise_if_shutdown_requested>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.raise_if_shutdown_requested
    :summary:
    ```
* - {py:obj}`configured_stopwaitsecs <archivebox.core.shutdown_util.configured_stopwaitsecs>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.configured_stopwaitsecs
    :summary:
    ```
* - {py:obj}`wait_popen_and_kill_children <archivebox.core.shutdown_util.wait_popen_and_kill_children>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.wait_popen_and_kill_children
    :summary:
    ```
* - {py:obj}`wait_psutil_and_kill_children <archivebox.core.shutdown_util.wait_psutil_and_kill_children>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.wait_psutil_and_kill_children
    :summary:
    ```
* - {py:obj}`kill_remaining_processes <archivebox.core.shutdown_util.kill_remaining_processes>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.kill_remaining_processes
    :summary:
    ```
* - {py:obj}`foreground_shutdown_signals <archivebox.core.shutdown_util.foreground_shutdown_signals>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.foreground_shutdown_signals
    :summary:
    ```
* - {py:obj}`foreground_parent_watchdog <archivebox.core.shutdown_util.foreground_parent_watchdog>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util.foreground_parent_watchdog
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_active_shutdown_state <archivebox.core.shutdown_util._active_shutdown_state>`
  - ```{autodoc2-docstring} archivebox.core.shutdown_util._active_shutdown_state
    :summary:
    ```
````

### API

`````{py:class} ShutdownSignalState
:canonical: archivebox.core.shutdown_util.ShutdownSignalState

```{autodoc2-docstring} archivebox.core.shutdown_util.ShutdownSignalState
```

````{py:attribute} signal_name
:canonical: archivebox.core.shutdown_util.ShutdownSignalState.signal_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.shutdown_util.ShutdownSignalState.signal_name
```

````

`````

````{py:data} _active_shutdown_state
:canonical: archivebox.core.shutdown_util._active_shutdown_state
:type: archivebox.core.shutdown_util.ShutdownSignalState | None
:value: >
   None

```{autodoc2-docstring} archivebox.core.shutdown_util._active_shutdown_state
```

````

````{py:function} raise_if_shutdown_requested() -> None
:canonical: archivebox.core.shutdown_util.raise_if_shutdown_requested

```{autodoc2-docstring} archivebox.core.shutdown_util.raise_if_shutdown_requested
```
````

````{py:function} configured_stopwaitsecs(workers: list[dict[str, str]] | tuple[dict[str, str], ...], *, default: int = 5, buffer: int = 5) -> int
:canonical: archivebox.core.shutdown_util.configured_stopwaitsecs

```{autodoc2-docstring} archivebox.core.shutdown_util.configured_stopwaitsecs
```
````

````{py:function} wait_popen_and_kill_children(proc: subprocess.Popen, children: list[psutil.Process], *, timeout: float, kill_timeout: float = 2.0) -> None
:canonical: archivebox.core.shutdown_util.wait_popen_and_kill_children

```{autodoc2-docstring} archivebox.core.shutdown_util.wait_popen_and_kill_children
```
````

````{py:function} wait_psutil_and_kill_children(proc: psutil.Process, children: list[psutil.Process], *, timeout: float, kill_timeout: float = 2.0) -> None
:canonical: archivebox.core.shutdown_util.wait_psutil_and_kill_children

```{autodoc2-docstring} archivebox.core.shutdown_util.wait_psutil_and_kill_children
```
````

````{py:function} kill_remaining_processes(processes: list[psutil.Process], *, timeout: float = 2.0) -> None
:canonical: archivebox.core.shutdown_util.kill_remaining_processes

```{autodoc2-docstring} archivebox.core.shutdown_util.kill_remaining_processes
```
````

````{py:function} foreground_shutdown_signals(handled_signals: tuple[signal.Signals, ...] = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM), *, first_signal_message: str | None = '\n[🛑] Got {signal_name}, stopping gracefully...\n', on_signal: collections.abc.Callable[[signal.Signals], None] | None = None, raise_on_first_signal: bool = True) -> collections.abc.Iterator[archivebox.core.shutdown_util.ShutdownSignalState]
:canonical: archivebox.core.shutdown_util.foreground_shutdown_signals

```{autodoc2-docstring} archivebox.core.shutdown_util.foreground_shutdown_signals
```
````

````{py:function} foreground_parent_watchdog(*, enabled: bool = True, check_interval: float = 2.0, shutdown_signal: signal.Signals = signal.SIGTERM) -> collections.abc.Iterator[None]
:canonical: archivebox.core.shutdown_util.foreground_parent_watchdog

```{autodoc2-docstring} archivebox.core.shutdown_util.foreground_parent_watchdog
```
````
