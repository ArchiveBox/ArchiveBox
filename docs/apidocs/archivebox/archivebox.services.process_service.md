# {py:mod}`archivebox.services.process_service`

```{py:module} archivebox.services.process_service
```

```{autodoc2-docstring} archivebox.services.process_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ProcessService <archivebox.services.process_service.ProcessService>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`parse_event_datetime <archivebox.services.process_service.parse_event_datetime>`
  - ```{autodoc2-docstring} archivebox.services.process_service.parse_event_datetime
    :summary:
    ```
* - {py:obj}`current_network_interface_with_machine <archivebox.services.process_service.current_network_interface_with_machine>`
  - ```{autodoc2-docstring} archivebox.services.process_service.current_network_interface_with_machine
    :summary:
    ```
* - {py:obj}`normalize_process_env <archivebox.services.process_service.normalize_process_env>`
  - ```{autodoc2-docstring} archivebox.services.process_service.normalize_process_env
    :summary:
    ```
````

### API

````{py:function} parse_event_datetime(value: str | None)
:canonical: archivebox.services.process_service.parse_event_datetime

```{autodoc2-docstring} archivebox.services.process_service.parse_event_datetime
```
````

````{py:function} current_network_interface_with_machine()
:canonical: archivebox.services.process_service.current_network_interface_with_machine

```{autodoc2-docstring} archivebox.services.process_service.current_network_interface_with_machine
```
````

````{py:function} normalize_process_env(env: dict) -> dict
:canonical: archivebox.services.process_service.normalize_process_env

```{autodoc2-docstring} archivebox.services.process_service.normalize_process_env
```
````

`````{py:class} ProcessService(bus)
:canonical: archivebox.services.process_service.ProcessService

Bases: {py:obj}`abx_dl.services.base.BaseService`

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.process_service.ProcessService.LISTENS_TO
:type: typing.ClassVar[list[type[abxbus.BaseEvent]]]
:value: >
   None

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.process_service.ProcessService.EMITS
:type: typing.ClassVar[list[type[abxbus.BaseEvent]]]
:value: >
   []

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.EMITS
```

````

````{py:method} current_iface()
:canonical: archivebox.services.process_service.ProcessService.current_iface
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.current_iface
```

````

````{py:method} on_ProcessStartedEvent__save_to_db(event: abx_dl.events.ProcessStartedEvent) -> None
:canonical: archivebox.services.process_service.ProcessService.on_ProcessStartedEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.on_ProcessStartedEvent__save_to_db
```

````

````{py:method} _completed_worker_loop() -> None
:canonical: archivebox.services.process_service.ProcessService._completed_worker_loop
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService._completed_worker_loop
```

````

````{py:method} _ensure_completed_worker() -> None
:canonical: archivebox.services.process_service.ProcessService._ensure_completed_worker

```{autodoc2-docstring} archivebox.services.process_service.ProcessService._ensure_completed_worker
```

````

````{py:method} on_ProcessCompletedEvent__save_to_db(event: abx_dl.events.ProcessCompletedEvent) -> None
:canonical: archivebox.services.process_service.ProcessService.on_ProcessCompletedEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.on_ProcessCompletedEvent__save_to_db
```

````

````{py:method} flush_completed() -> None
:canonical: archivebox.services.process_service.ProcessService.flush_completed
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.flush_completed
```

````

````{py:method} on_CrawlCleanupEvent__flush_completed(event: abx_dl.events.CrawlCleanupEvent) -> None
:canonical: archivebox.services.process_service.ProcessService.on_CrawlCleanupEvent__flush_completed
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.on_CrawlCleanupEvent__flush_completed
```

````

````{py:method} on_CrawlCompletedEvent__flush_completed(event: abx_dl.events.CrawlCompletedEvent) -> None
:canonical: archivebox.services.process_service.ProcessService.on_CrawlCompletedEvent__flush_completed
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService.on_CrawlCompletedEvent__flush_completed
```

````

````{py:method} _save_completed_process_to_db(event: abx_dl.events.ProcessCompletedEvent) -> None
:canonical: archivebox.services.process_service.ProcessService._save_completed_process_to_db
:async:

```{autodoc2-docstring} archivebox.services.process_service.ProcessService._save_completed_process_to_db
```

````

`````
