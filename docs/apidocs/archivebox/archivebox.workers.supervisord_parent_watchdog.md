# {py:mod}`archivebox.workers.supervisord_parent_watchdog`

```{py:module} archivebox.workers.supervisord_parent_watchdog
```

```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`matching_process <archivebox.workers.supervisord_parent_watchdog.matching_process>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.matching_process
    :summary:
    ```
* - {py:obj}`run_watchdog <archivebox.workers.supervisord_parent_watchdog.run_watchdog>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.run_watchdog
    :summary:
    ```
* - {py:obj}`main <archivebox.workers.supervisord_parent_watchdog.main>`
  - ```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.main
    :summary:
    ```
````

### API

````{py:function} matching_process(pid: int, started_at: float) -> psutil.Process | None
:canonical: archivebox.workers.supervisord_parent_watchdog.matching_process

```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.matching_process
```
````

````{py:function} run_watchdog(*, owner_pid: int, owner_started_at: float, supervisord_pid: int, supervisord_started_at: float, interval: float = 1.0) -> None
:canonical: archivebox.workers.supervisord_parent_watchdog.run_watchdog

```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.run_watchdog
```
````

````{py:function} main() -> None
:canonical: archivebox.workers.supervisord_parent_watchdog.main

```{autodoc2-docstring} archivebox.workers.supervisord_parent_watchdog.main
```
````
