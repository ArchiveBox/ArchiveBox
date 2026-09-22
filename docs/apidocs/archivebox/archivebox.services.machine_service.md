# {py:mod}`archivebox.services.machine_service`

```{py:module} archivebox.services.machine_service
```

```{autodoc2-docstring} archivebox.services.machine_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineService <archivebox.services.machine_service.MachineService>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_is_binary_event_key <archivebox.services.machine_service._is_binary_event_key>`
  - ```{autodoc2-docstring} archivebox.services.machine_service._is_binary_event_key
    :summary:
    ```
* - {py:obj}`_strip_to_binary_keys <archivebox.services.machine_service._strip_to_binary_keys>`
  - ```{autodoc2-docstring} archivebox.services.machine_service._strip_to_binary_keys
    :summary:
    ```
````

### API

````{py:function} _is_binary_event_key(key: str) -> bool
:canonical: archivebox.services.machine_service._is_binary_event_key

```{autodoc2-docstring} archivebox.services.machine_service._is_binary_event_key
```
````

````{py:function} _strip_to_binary_keys(config: dict[str, typing.Any] | None) -> dict[str, typing.Any]
:canonical: archivebox.services.machine_service._strip_to_binary_keys

```{autodoc2-docstring} archivebox.services.machine_service._strip_to_binary_keys
```
````

`````{py:class} MachineService(bus)
:canonical: archivebox.services.machine_service.MachineService

Bases: {py:obj}`abx_dl.services.base.BaseService`

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.machine_service.MachineService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.machine_service.MachineService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.machine_service.MachineService.EMITS
:value: >
   []

```{autodoc2-docstring} archivebox.services.machine_service.MachineService.EMITS
```

````

````{py:method} on_MachineEvent__save_to_db(event: abx_dl.events.MachineEvent) -> None
:canonical: archivebox.services.machine_service.MachineService.on_MachineEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.machine_service.MachineService.on_MachineEvent__save_to_db
```

````

`````
