# {py:mod}`archivebox.importers.service`

```{py:module} archivebox.importers.service
```

```{autodoc2-docstring} archivebox.importers.service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Cancellation <archivebox.importers.service.Cancellation>`
  - ```{autodoc2-docstring} archivebox.importers.service.Cancellation
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`enqueue <archivebox.importers.service.enqueue>`
  - ```{autodoc2-docstring} archivebox.importers.service.enqueue
    :summary:
    ```
* - {py:obj}`pause <archivebox.importers.service.pause>`
  - ```{autodoc2-docstring} archivebox.importers.service.pause
    :summary:
    ```
* - {py:obj}`enqueue_due <archivebox.importers.service.enqueue_due>`
  - ```{autodoc2-docstring} archivebox.importers.service.enqueue_due
    :summary:
    ```
* - {py:obj}`_read_output <archivebox.importers.service._read_output>`
  - ```{autodoc2-docstring} archivebox.importers.service._read_output
    :summary:
    ```
* - {py:obj}`_finish <archivebox.importers.service._finish>`
  - ```{autodoc2-docstring} archivebox.importers.service._finish
    :summary:
    ```
* - {py:obj}`run_next_importer <archivebox.importers.service.run_next_importer>`
  - ```{autodoc2-docstring} archivebox.importers.service.run_next_importer
    :summary:
    ```
* - {py:obj}`recover_interrupted <archivebox.importers.service.recover_interrupted>`
  - ```{autodoc2-docstring} archivebox.importers.service.recover_interrupted
    :summary:
    ```
* - {py:obj}`_background_run <archivebox.importers.service._background_run>`
  - ```{autodoc2-docstring} archivebox.importers.service._background_run
    :summary:
    ```
* - {py:obj}`shutdown <archivebox.importers.service.shutdown>`
  - ```{autodoc2-docstring} archivebox.importers.service.shutdown
    :summary:
    ```
* - {py:obj}`tick <archivebox.importers.service.tick>`
  - ```{autodoc2-docstring} archivebox.importers.service.tick
    :summary:
    ```
* - {py:obj}`save_source <archivebox.importers.service.save_source>`
  - ```{autodoc2-docstring} archivebox.importers.service.save_source
    :summary:
    ```
* - {py:obj}`source_action <archivebox.importers.service.source_action>`
  - ```{autodoc2-docstring} archivebox.importers.service.source_action
    :summary:
    ```
* - {py:obj}`delete_source <archivebox.importers.service.delete_source>`
  - ```{autodoc2-docstring} archivebox.importers.service.delete_source
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`logger <archivebox.importers.service.logger>`
  - ```{autodoc2-docstring} archivebox.importers.service.logger
    :summary:
    ```
* - {py:obj}`ACTIVE_STATUSES <archivebox.importers.service.ACTIVE_STATUSES>`
  - ```{autodoc2-docstring} archivebox.importers.service.ACTIVE_STATUSES
    :summary:
    ```
* - {py:obj}`_thread <archivebox.importers.service._thread>`
  - ```{autodoc2-docstring} archivebox.importers.service._thread
    :summary:
    ```
* - {py:obj}`_stop <archivebox.importers.service._stop>`
  - ```{autodoc2-docstring} archivebox.importers.service._stop
    :summary:
    ```
````

### API

````{py:data} logger
:canonical: archivebox.importers.service.logger
:value: >
   'getLogger(...)'

```{autodoc2-docstring} archivebox.importers.service.logger
```

````

````{py:data} ACTIVE_STATUSES
:canonical: archivebox.importers.service.ACTIVE_STATUSES
:value: >
   ()

```{autodoc2-docstring} archivebox.importers.service.ACTIVE_STATUSES
```

````

````{py:function} enqueue(source: archivebox.importers.models.ImporterSource, action: str) -> archivebox.importers.models.ImporterRun
:canonical: archivebox.importers.service.enqueue

```{autodoc2-docstring} archivebox.importers.service.enqueue
```
````

````{py:function} pause(source: archivebox.importers.models.ImporterSource) -> None
:canonical: archivebox.importers.service.pause

```{autodoc2-docstring} archivebox.importers.service.pause
```
````

````{py:function} enqueue_due() -> None
:canonical: archivebox.importers.service.enqueue_due

```{autodoc2-docstring} archivebox.importers.service.enqueue_due
```
````

`````{py:class} Cancellation(run_id, stop_event=None)
:canonical: archivebox.importers.service.Cancellation

```{autodoc2-docstring} archivebox.importers.service.Cancellation
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.importers.service.Cancellation.__init__
```

````{py:method} is_set()
:canonical: archivebox.importers.service.Cancellation.is_set

```{autodoc2-docstring} archivebox.importers.service.Cancellation.is_set
```

````

`````

````{py:function} _read_output(run, command, config, output_dir: pathlib.Path, cancellation)
:canonical: archivebox.importers.service._read_output

```{autodoc2-docstring} archivebox.importers.service._read_output
```
````

````{py:function} _finish(run, items, result)
:canonical: archivebox.importers.service._finish

```{autodoc2-docstring} archivebox.importers.service._finish
```
````

````{py:function} run_next_importer(stop_event=None, *, run_id=None) -> bool
:canonical: archivebox.importers.service.run_next_importer

```{autodoc2-docstring} archivebox.importers.service.run_next_importer
```
````

````{py:function} recover_interrupted() -> None
:canonical: archivebox.importers.service.recover_interrupted

```{autodoc2-docstring} archivebox.importers.service.recover_interrupted
```
````

````{py:data} _thread
:canonical: archivebox.importers.service._thread
:value: >
   None

```{autodoc2-docstring} archivebox.importers.service._thread
```

````

````{py:data} _stop
:canonical: archivebox.importers.service._stop
:value: >
   'Event(...)'

```{autodoc2-docstring} archivebox.importers.service._stop
```

````

````{py:function} _background_run()
:canonical: archivebox.importers.service._background_run

```{autodoc2-docstring} archivebox.importers.service._background_run
```
````

````{py:function} shutdown()
:canonical: archivebox.importers.service.shutdown

```{autodoc2-docstring} archivebox.importers.service.shutdown
```
````

````{py:function} tick(*, daemon: bool) -> bool
:canonical: archivebox.importers.service.tick

```{autodoc2-docstring} archivebox.importers.service.tick
```
````

````{py:function} save_source(source, values)
:canonical: archivebox.importers.service.save_source

```{autodoc2-docstring} archivebox.importers.service.save_source
```
````

````{py:function} source_action(source, action)
:canonical: archivebox.importers.service.source_action

```{autodoc2-docstring} archivebox.importers.service.source_action
```
````

````{py:function} delete_source(source)
:canonical: archivebox.importers.service.delete_source

```{autodoc2-docstring} archivebox.importers.service.delete_source
```
````
