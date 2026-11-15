# {py:mod}`archivebox.services.resource_admission`

```{py:module} archivebox.services.resource_admission
```

```{autodoc2-docstring} archivebox.services.resource_admission
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ResourceAdmission <archivebox.services.resource_admission.ResourceAdmission>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`zram_swap_identifiers <archivebox.services.resource_admission.zram_swap_identifiers>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.zram_swap_identifiers
    :summary:
    ```
* - {py:obj}`swap_source_identifiers <archivebox.services.resource_admission.swap_source_identifiers>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.swap_source_identifiers
    :summary:
    ```
* - {py:obj}`disk_backed_swap_free_bytes <archivebox.services.resource_admission.disk_backed_swap_free_bytes>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.disk_backed_swap_free_bytes
    :summary:
    ```
* - {py:obj}`host_swap_free_bytes <archivebox.services.resource_admission.host_swap_free_bytes>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.host_swap_free_bytes
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`RESOURCE_RECHECK_SECONDS <archivebox.services.resource_admission.RESOURCE_RECHECK_SECONDS>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.RESOURCE_RECHECK_SECONDS
    :summary:
    ```
* - {py:obj}`MEMORY_FULL_STALL_PERCENT <archivebox.services.resource_admission.MEMORY_FULL_STALL_PERCENT>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.MEMORY_FULL_STALL_PERCENT
    :summary:
    ```
* - {py:obj}`IO_FULL_STALL_PERCENT <archivebox.services.resource_admission.IO_FULL_STALL_PERCENT>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.IO_FULL_STALL_PERCENT
    :summary:
    ```
* - {py:obj}`CPU_SOME_STALL_PERCENT <archivebox.services.resource_admission.CPU_SOME_STALL_PERCENT>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.CPU_SOME_STALL_PERCENT
    :summary:
    ```
* - {py:obj}`ZRAM_DEVICE_NAME <archivebox.services.resource_admission.ZRAM_DEVICE_NAME>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.ZRAM_DEVICE_NAME
    :summary:
    ```
* - {py:obj}`resource_admission <archivebox.services.resource_admission.resource_admission>`
  - ```{autodoc2-docstring} archivebox.services.resource_admission.resource_admission
    :summary:
    ```
````

### API

````{py:data} RESOURCE_RECHECK_SECONDS
:canonical: archivebox.services.resource_admission.RESOURCE_RECHECK_SECONDS
:value: >
   2.0

```{autodoc2-docstring} archivebox.services.resource_admission.RESOURCE_RECHECK_SECONDS
```

````

````{py:data} MEMORY_FULL_STALL_PERCENT
:canonical: archivebox.services.resource_admission.MEMORY_FULL_STALL_PERCENT
:value: >
   10.0

```{autodoc2-docstring} archivebox.services.resource_admission.MEMORY_FULL_STALL_PERCENT
```

````

````{py:data} IO_FULL_STALL_PERCENT
:canonical: archivebox.services.resource_admission.IO_FULL_STALL_PERCENT
:value: >
   10.0

```{autodoc2-docstring} archivebox.services.resource_admission.IO_FULL_STALL_PERCENT
```

````

````{py:data} CPU_SOME_STALL_PERCENT
:canonical: archivebox.services.resource_admission.CPU_SOME_STALL_PERCENT
:value: >
   50.0

```{autodoc2-docstring} archivebox.services.resource_admission.CPU_SOME_STALL_PERCENT
```

````

````{py:data} ZRAM_DEVICE_NAME
:canonical: archivebox.services.resource_admission.ZRAM_DEVICE_NAME
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.services.resource_admission.ZRAM_DEVICE_NAME
```

````

````{py:function} zram_swap_identifiers(sys_block: pathlib.Path = Path('/sys/block')) -> set[str]
:canonical: archivebox.services.resource_admission.zram_swap_identifiers

```{autodoc2-docstring} archivebox.services.resource_admission.zram_swap_identifiers
```
````

````{py:function} swap_source_identifiers(filename: str) -> set[str]
:canonical: archivebox.services.resource_admission.swap_source_identifiers

```{autodoc2-docstring} archivebox.services.resource_admission.swap_source_identifiers
```
````

````{py:function} disk_backed_swap_free_bytes(swaps: str, zram_identifiers: set[str]) -> int
:canonical: archivebox.services.resource_admission.disk_backed_swap_free_bytes

```{autodoc2-docstring} archivebox.services.resource_admission.disk_backed_swap_free_bytes
```
````

````{py:function} host_swap_free_bytes(meminfo_swap_free: int) -> int
:canonical: archivebox.services.resource_admission.host_swap_free_bytes

```{autodoc2-docstring} archivebox.services.resource_admission.host_swap_free_bytes
```
````

`````{py:class} ResourceAdmission()
:canonical: archivebox.services.resource_admission.ResourceAdmission

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.__init__
```

````{py:method} cgroup_paths() -> list[pathlib.Path]
:canonical: archivebox.services.resource_admission.ResourceAdmission.cgroup_paths
:staticmethod:

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.cgroup_paths
```

````

````{py:method} snapshot_limit(configured: int) -> int
:canonical: archivebox.services.resource_admission.ResourceAdmission.snapshot_limit

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.snapshot_limit
```

````

````{py:method} concurrency_limit(ceiling: int, *, pressure: bool, now: float) -> int
:canonical: archivebox.services.resource_admission.ResourceAdmission.concurrency_limit

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.concurrency_limit
```

````

````{py:method} additional_snapshot_slots(configured: int, active: int, observed_cost: int | None, *, crawl_id: str | None = None, minimum_free: int = 0, active_memory: int | None = None) -> int
:canonical: archivebox.services.resource_admission.ResourceAdmission.additional_snapshot_slots

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.additional_snapshot_slots
```

````

````{py:method} slots_for_headroom(configured: int, active: int, observed_cost: int | None, available: int, *, active_memory: int | None = None) -> int
:canonical: archivebox.services.resource_admission.ResourceAdmission.slots_for_headroom
:staticmethod:

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.slots_for_headroom
```

````

````{py:method} memory_headroom(*, minimum_free: int = 0) -> int
:canonical: archivebox.services.resource_admission.ResourceAdmission.memory_headroom

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.memory_headroom
```

````

````{py:method} process_tree_memory() -> int | None
:canonical: archivebox.services.resource_admission.ResourceAdmission.process_tree_memory

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.process_tree_memory
```

````

````{py:method} observe_stalls(source: str, total: int, avg10: float, sampled_at: float, threshold: float) -> bool
:canonical: archivebox.services.resource_admission.ResourceAdmission.observe_stalls

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.observe_stalls
```

````

````{py:method} observe_cpu_throttling(source: str, throttled: int, sampled_at: float, period_usec: int) -> bool
:canonical: archivebox.services.resource_admission.ResourceAdmission.observe_cpu_throttling

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.observe_cpu_throttling
```

````

````{py:method} resource_pressure(*, required_memory: int | None = None, minimum_free: int = 0) -> str | None
:canonical: archivebox.services.resource_admission.ResourceAdmission.resource_pressure

```{autodoc2-docstring} archivebox.services.resource_admission.ResourceAdmission.resource_pressure
```

````

`````

````{py:data} resource_admission
:canonical: archivebox.services.resource_admission.resource_admission
:value: >
   'ResourceAdmission(...)'

```{autodoc2-docstring} archivebox.services.resource_admission.resource_admission
```

````
