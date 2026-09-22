# {py:mod}`archivebox.services.binary_service`

```{py:module} archivebox.services.binary_service
```

```{autodoc2-docstring} archivebox.services.binary_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveBoxDBBinaryCacheBackend <archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend>`
  - ```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend
    :summary:
    ```
* - {py:obj}`ArchiveBoxBinaryService <archivebox.services.binary_service.ArchiveBoxBinaryService>`
  - ```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_provider_names <archivebox.services.binary_service._provider_names>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._provider_names
    :summary:
    ```
* - {py:obj}`_binproviders_to_str <archivebox.services.binary_service._binproviders_to_str>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._binproviders_to_str
    :summary:
    ```
* - {py:obj}`_providers_for_names <archivebox.services.binary_service._providers_for_names>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._providers_for_names
    :summary:
    ```
* - {py:obj}`_provider_for_name <archivebox.services.binary_service._provider_for_name>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._provider_for_name
    :summary:
    ```
* - {py:obj}`_mark_binary_queued <archivebox.services.binary_service._mark_binary_queued>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._mark_binary_queued
    :summary:
    ```
* - {py:obj}`_persisted_overrides_for_request <archivebox.services.binary_service._persisted_overrides_for_request>`
  - ```{autodoc2-docstring} archivebox.services.binary_service._persisted_overrides_for_request
    :summary:
    ```
````

### API

`````{py:class} ArchiveBoxDBBinaryCacheBackend
:canonical: archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend
```

````{py:method} get(request: abxpkg.binary_service.BinaryRequestEvent) -> abxpkg.Binary | None
:canonical: archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.get
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.get
```

````

````{py:method} set(request: abxpkg.binary_service.BinaryRequestEvent | None, binary: abxpkg.Binary) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.set
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.set
```

````

````{py:method} invalidate(request: abxpkg.binary_service.BinaryRequestEvent, binary: abxpkg.Binary, reason: str) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.invalidate
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxDBBinaryCacheBackend.invalidate
```

````

`````

`````{py:class} ArchiveBoxBinaryService(bus: abxbus.EventBus)
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService

Bases: {py:obj}`abx_dl.services.base.BaseService`

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.__init__
```

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.EMITS
:type: list[type[abxbus.BaseEvent]]
:value: >
   []

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.EMITS
```

````

````{py:method} on_BinaryRequestEvent__project_process(request: abxpkg.binary_service.BinaryRequestEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryRequestEvent__project_process
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryRequestEvent__project_process
```

````

````{py:method} on_BinaryEvent__finalize_process(event: abxpkg.binary_service.BinaryEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryEvent__finalize_process
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryEvent__finalize_process
```

````

````{py:method} _get_or_create_binary(machine, binary_name: str, request: abxpkg.binary_service.BinaryRequestEvent)
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._get_or_create_binary
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._get_or_create_binary
```

````

````{py:method} _process_cmd(request: abxpkg.binary_service.BinaryRequestEvent) -> list[str]
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._process_cmd

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._process_cmd
```

````

````{py:method} _binary_event_json(event: abxpkg.binary_service.BinaryEvent, binary) -> dict[str, typing.Any]
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._binary_event_json

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._binary_event_json
```

````

````{py:method} _finalize_missing_process(request: abxpkg.binary_service.BinaryRequestEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._finalize_missing_process
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._finalize_missing_process
```

````

````{py:method} _finalize_request_when_done(request: abxpkg.binary_service.BinaryRequestEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._finalize_request_when_done
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._finalize_request_when_done
```

````

````{py:method} _schedule_missing_finalize(request: abxpkg.binary_service.BinaryRequestEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._schedule_missing_finalize

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._schedule_missing_finalize
```

````

````{py:method} flush_missing_finalizers() -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.flush_missing_finalizers
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.flush_missing_finalizers
```

````

````{py:method} on_BinaryRequestEvent__schedule_missing_finalize(request: abxpkg.binary_service.BinaryRequestEvent) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryRequestEvent__schedule_missing_finalize
:async:

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService.on_BinaryRequestEvent__schedule_missing_finalize
```

````

````{py:method} _process_output_dir(binary, request: abxpkg.binary_service.BinaryRequestEvent) -> pathlib.Path
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._process_output_dir

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._process_output_dir
```

````

````{py:method} _write_binary_index(binary, process, output_dir: pathlib.Path) -> None
:canonical: archivebox.services.binary_service.ArchiveBoxBinaryService._write_binary_index

```{autodoc2-docstring} archivebox.services.binary_service.ArchiveBoxBinaryService._write_binary_index
```

````

`````

````{py:function} _provider_names(binproviders: str | list[str] | None) -> list[str]
:canonical: archivebox.services.binary_service._provider_names

```{autodoc2-docstring} archivebox.services.binary_service._provider_names
```
````

````{py:function} _binproviders_to_str(binproviders: str | list[str] | None) -> str
:canonical: archivebox.services.binary_service._binproviders_to_str

```{autodoc2-docstring} archivebox.services.binary_service._binproviders_to_str
```
````

````{py:function} _providers_for_names(names: list[str]) -> list[abxpkg.BinProvider]
:canonical: archivebox.services.binary_service._providers_for_names

```{autodoc2-docstring} archivebox.services.binary_service._providers_for_names
```
````

````{py:function} _provider_for_name(provider_name: str, binary_name: str, overrides: dict[str, typing.Any] | None) -> abxpkg.BinProvider | None
:canonical: archivebox.services.binary_service._provider_for_name

```{autodoc2-docstring} archivebox.services.binary_service._provider_for_name
```
````

````{py:function} _mark_binary_queued(binary) -> None
:canonical: archivebox.services.binary_service._mark_binary_queued
:async:

```{autodoc2-docstring} archivebox.services.binary_service._mark_binary_queued
```
````

````{py:function} _persisted_overrides_for_request(request: abxpkg.binary_service.BinaryRequestEvent | None) -> dict[str, typing.Any]
:canonical: archivebox.services.binary_service._persisted_overrides_for_request

```{autodoc2-docstring} archivebox.services.binary_service._persisted_overrides_for_request
```
````
