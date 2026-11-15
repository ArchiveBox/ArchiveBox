# {py:mod}`archivebox.crawls.locks`

```{py:module} archivebox.crawls.locks
```

```{autodoc2-docstring} archivebox.crawls.locks
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_LifecycleLockState <archivebox.crawls.locks._LifecycleLockState>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._LifecycleLockState
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`lifecycle_locks_held <archivebox.crawls.locks.lifecycle_locks_held>`
  - ```{autodoc2-docstring} archivebox.crawls.locks.lifecycle_locks_held
    :summary:
    ```
* - {py:obj}`after_lifecycle_locks <archivebox.crawls.locks.after_lifecycle_locks>`
  - ```{autodoc2-docstring} archivebox.crawls.locks.after_lifecycle_locks
    :summary:
    ```
* - {py:obj}`crawl_lifecycle_lock_path <archivebox.crawls.locks.crawl_lifecycle_lock_path>`
  - ```{autodoc2-docstring} archivebox.crawls.locks.crawl_lifecycle_lock_path
    :summary:
    ```
* - {py:obj}`_lifecycle_lock <archivebox.crawls.locks._lifecycle_lock>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._lifecycle_lock
    :summary:
    ```
* - {py:obj}`crawl_lifecycle_lock <archivebox.crawls.locks.crawl_lifecycle_lock>`
  - ```{autodoc2-docstring} archivebox.crawls.locks.crawl_lifecycle_lock
    :summary:
    ```
* - {py:obj}`binary_lifecycle_lock <archivebox.crawls.locks.binary_lifecycle_lock>`
  - ```{autodoc2-docstring} archivebox.crawls.locks.binary_lifecycle_lock
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_registry_lock <archivebox.crawls.locks._registry_lock>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._registry_lock
    :summary:
    ```
* - {py:obj}`_registry_pid <archivebox.crawls.locks._registry_pid>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._registry_pid
    :summary:
    ```
* - {py:obj}`_registry <archivebox.crawls.locks._registry>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._registry
    :summary:
    ```
* - {py:obj}`_held_locks <archivebox.crawls.locks._held_locks>`
  - ```{autodoc2-docstring} archivebox.crawls.locks._held_locks
    :summary:
    ```
````

### API

````{py:class} _LifecycleLockState()
:canonical: archivebox.crawls.locks._LifecycleLockState

```{autodoc2-docstring} archivebox.crawls.locks._LifecycleLockState
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.crawls.locks._LifecycleLockState.__init__
```

````

````{py:data} _registry_lock
:canonical: archivebox.crawls.locks._registry_lock
:value: >
   'Lock(...)'

```{autodoc2-docstring} archivebox.crawls.locks._registry_lock
```

````

````{py:data} _registry_pid
:canonical: archivebox.crawls.locks._registry_pid
:value: >
   'getpid(...)'

```{autodoc2-docstring} archivebox.crawls.locks._registry_pid
```

````

````{py:data} _registry
:canonical: archivebox.crawls.locks._registry
:type: dict[str, archivebox.crawls.locks._LifecycleLockState]
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.locks._registry
```

````

````{py:data} _held_locks
:canonical: archivebox.crawls.locks._held_locks
:type: contextvars.ContextVar[tuple[archivebox.crawls.locks._LifecycleLockState, ...]]
:value: >
   'ContextVar(...)'

```{autodoc2-docstring} archivebox.crawls.locks._held_locks
```

````

````{py:function} lifecycle_locks_held() -> bool
:canonical: archivebox.crawls.locks.lifecycle_locks_held

```{autodoc2-docstring} archivebox.crawls.locks.lifecycle_locks_held
```
````

````{py:function} after_lifecycle_locks(callback: collections.abc.Callable[[], None]) -> bool
:canonical: archivebox.crawls.locks.after_lifecycle_locks

```{autodoc2-docstring} archivebox.crawls.locks.after_lifecycle_locks
```
````

````{py:function} crawl_lifecycle_lock_path(crawl_id: str) -> pathlib.Path
:canonical: archivebox.crawls.locks.crawl_lifecycle_lock_path

```{autodoc2-docstring} archivebox.crawls.locks.crawl_lifecycle_lock_path
```
````

````{py:function} _lifecycle_lock(key: str, lock_path: pathlib.Path) -> collections.abc.Iterator[None]
:canonical: archivebox.crawls.locks._lifecycle_lock

```{autodoc2-docstring} archivebox.crawls.locks._lifecycle_lock
```
````

````{py:function} crawl_lifecycle_lock(crawl_id: str) -> collections.abc.Iterator[None]
:canonical: archivebox.crawls.locks.crawl_lifecycle_lock

```{autodoc2-docstring} archivebox.crawls.locks.crawl_lifecycle_lock
```
````

````{py:function} binary_lifecycle_lock(binary_id: str) -> collections.abc.Iterator[None]
:canonical: archivebox.crawls.locks.binary_lifecycle_lock

```{autodoc2-docstring} archivebox.crawls.locks.binary_lifecycle_lock
```
````
