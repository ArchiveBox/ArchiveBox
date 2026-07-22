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
