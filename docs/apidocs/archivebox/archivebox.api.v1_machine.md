# {py:mod}`archivebox.api.v1_machine`

```{py:module} archivebox.api.v1_machine
```

```{autodoc2-docstring} archivebox.api.v1_machine
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineSchema <archivebox.api.v1_machine.MachineSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema
    :summary:
    ```
* - {py:obj}`MachineFilterSchema <archivebox.api.v1_machine.MachineFilterSchema>`
  -
* - {py:obj}`BinarySchema <archivebox.api.v1_machine.BinarySchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema
    :summary:
    ```
* - {py:obj}`BinaryFilterSchema <archivebox.api.v1_machine.BinaryFilterSchema>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_machines <archivebox.api.v1_machine.get_machines>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_machines
    :summary:
    ```
* - {py:obj}`get_current_machine <archivebox.api.v1_machine.get_current_machine>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_current_machine
    :summary:
    ```
* - {py:obj}`get_machine <archivebox.api.v1_machine.get_machine>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_machine
    :summary:
    ```
* - {py:obj}`get_binaries <archivebox.api.v1_machine.get_binaries>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_binaries
    :summary:
    ```
* - {py:obj}`get_binary <archivebox.api.v1_machine.get_binary>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_binary
    :summary:
    ```
* - {py:obj}`get_binaries_by_name <archivebox.api.v1_machine.get_binaries_by_name>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.get_binaries_by_name
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_machine.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_machine.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_machine.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_machine.router
```

````

`````{py:class} MachineSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_machine.MachineSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.__init__
```

````{py:attribute} TYPE
:canonical: archivebox.api.v1_machine.MachineSchema.TYPE
:type: str
:value: >
   'machine.Machine'

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_machine.MachineSchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.id
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_machine.MachineSchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_machine.MachineSchema.modified_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.modified_at
```

````

````{py:attribute} guid
:canonical: archivebox.api.v1_machine.MachineSchema.guid
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.guid
```

````

````{py:attribute} hostname
:canonical: archivebox.api.v1_machine.MachineSchema.hostname
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hostname
```

````

````{py:attribute} hw_in_docker
:canonical: archivebox.api.v1_machine.MachineSchema.hw_in_docker
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hw_in_docker
```

````

````{py:attribute} hw_in_vm
:canonical: archivebox.api.v1_machine.MachineSchema.hw_in_vm
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hw_in_vm
```

````

````{py:attribute} hw_manufacturer
:canonical: archivebox.api.v1_machine.MachineSchema.hw_manufacturer
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hw_manufacturer
```

````

````{py:attribute} hw_product
:canonical: archivebox.api.v1_machine.MachineSchema.hw_product
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hw_product
```

````

````{py:attribute} hw_uuid
:canonical: archivebox.api.v1_machine.MachineSchema.hw_uuid
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.hw_uuid
```

````

````{py:attribute} os_arch
:canonical: archivebox.api.v1_machine.MachineSchema.os_arch
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.os_arch
```

````

````{py:attribute} os_family
:canonical: archivebox.api.v1_machine.MachineSchema.os_family
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.os_family
```

````

````{py:attribute} os_platform
:canonical: archivebox.api.v1_machine.MachineSchema.os_platform
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.os_platform
```

````

````{py:attribute} os_release
:canonical: archivebox.api.v1_machine.MachineSchema.os_release
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.os_release
```

````

````{py:attribute} os_kernel
:canonical: archivebox.api.v1_machine.MachineSchema.os_kernel
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.os_kernel
```

````

````{py:attribute} stats
:canonical: archivebox.api.v1_machine.MachineSchema.stats
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.stats
```

````

````{py:attribute} num_uses_succeeded
:canonical: archivebox.api.v1_machine.MachineSchema.num_uses_succeeded
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.num_uses_succeeded
```

````

````{py:attribute} num_uses_failed
:canonical: archivebox.api.v1_machine.MachineSchema.num_uses_failed
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineSchema.num_uses_failed
```

````

`````

`````{py:class} MachineFilterSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_machine.MachineFilterSchema

Bases: {py:obj}`ninja.FilterSchema`

````{py:attribute} id
:canonical: archivebox.api.v1_machine.MachineFilterSchema.id
:type: typing.Annotated[str | None, FilterLookup('id__startswith')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.id
```

````

````{py:attribute} hostname
:canonical: archivebox.api.v1_machine.MachineFilterSchema.hostname
:type: typing.Annotated[str | None, FilterLookup('hostname__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.hostname
```

````

````{py:attribute} os_platform
:canonical: archivebox.api.v1_machine.MachineFilterSchema.os_platform
:type: typing.Annotated[str | None, FilterLookup('os_platform__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.os_platform
```

````

````{py:attribute} os_arch
:canonical: archivebox.api.v1_machine.MachineFilterSchema.os_arch
:type: typing.Annotated[str | None, FilterLookup('os_arch')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.os_arch
```

````

````{py:attribute} hw_in_docker
:canonical: archivebox.api.v1_machine.MachineFilterSchema.hw_in_docker
:type: typing.Annotated[bool | None, FilterLookup('hw_in_docker')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.hw_in_docker
```

````

````{py:attribute} hw_in_vm
:canonical: archivebox.api.v1_machine.MachineFilterSchema.hw_in_vm
:type: typing.Annotated[bool | None, FilterLookup('hw_in_vm')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.hw_in_vm
```

````

````{py:attribute} bin_providers
:canonical: archivebox.api.v1_machine.MachineFilterSchema.bin_providers
:type: typing.Annotated[str | None, FilterLookup('bin_providers__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.MachineFilterSchema.bin_providers
```

````

`````

`````{py:class} BinarySchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_machine.BinarySchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.__init__
```

````{py:attribute} TYPE
:canonical: archivebox.api.v1_machine.BinarySchema.TYPE
:type: str
:value: >
   'machine.Binary'

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_machine.BinarySchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.id
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_machine.BinarySchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_machine.BinarySchema.modified_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.modified_at
```

````

````{py:attribute} machine_id
:canonical: archivebox.api.v1_machine.BinarySchema.machine_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.machine_id
```

````

````{py:attribute} machine_hostname
:canonical: archivebox.api.v1_machine.BinarySchema.machine_hostname
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.machine_hostname
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_machine.BinarySchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.name
```

````

````{py:attribute} binproviders
:canonical: archivebox.api.v1_machine.BinarySchema.binproviders
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.binproviders
```

````

````{py:attribute} binprovider
:canonical: archivebox.api.v1_machine.BinarySchema.binprovider
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.binprovider
```

````

````{py:attribute} abspath
:canonical: archivebox.api.v1_machine.BinarySchema.abspath
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.abspath
```

````

````{py:attribute} version
:canonical: archivebox.api.v1_machine.BinarySchema.version
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.version
```

````

````{py:attribute} sha256
:canonical: archivebox.api.v1_machine.BinarySchema.sha256
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.sha256
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_machine.BinarySchema.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.status
```

````

````{py:attribute} is_valid
:canonical: archivebox.api.v1_machine.BinarySchema.is_valid
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.is_valid
```

````

````{py:attribute} num_uses_succeeded
:canonical: archivebox.api.v1_machine.BinarySchema.num_uses_succeeded
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.num_uses_succeeded
```

````

````{py:attribute} num_uses_failed
:canonical: archivebox.api.v1_machine.BinarySchema.num_uses_failed
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.num_uses_failed
```

````

````{py:method} resolve_machine_hostname(obj) -> str
:canonical: archivebox.api.v1_machine.BinarySchema.resolve_machine_hostname
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.resolve_machine_hostname
```

````

````{py:method} resolve_is_valid(obj) -> bool
:canonical: archivebox.api.v1_machine.BinarySchema.resolve_is_valid
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_machine.BinarySchema.resolve_is_valid
```

````

`````

`````{py:class} BinaryFilterSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_machine.BinaryFilterSchema

Bases: {py:obj}`ninja.FilterSchema`

````{py:attribute} id
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.id
:type: typing.Annotated[str | None, FilterLookup('id__startswith')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.name
:type: typing.Annotated[str | None, FilterLookup('name__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.name
```

````

````{py:attribute} binprovider
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.binprovider
:type: typing.Annotated[str | None, FilterLookup('binprovider')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.binprovider
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.status
:type: typing.Annotated[str | None, FilterLookup('status')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.status
```

````

````{py:attribute} machine_id
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.machine_id
:type: typing.Annotated[str | None, FilterLookup('machine_id__startswith')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.machine_id
```

````

````{py:attribute} version
:canonical: archivebox.api.v1_machine.BinaryFilterSchema.version
:type: typing.Annotated[str | None, FilterLookup('version__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_machine.BinaryFilterSchema.version
```

````

`````

````{py:function} get_machines(request: django.http.HttpRequest, filters: ninja.Query[archivebox.api.v1_machine.MachineFilterSchema])
:canonical: archivebox.api.v1_machine.get_machines

```{autodoc2-docstring} archivebox.api.v1_machine.get_machines
```
````

````{py:function} get_current_machine(request: django.http.HttpRequest)
:canonical: archivebox.api.v1_machine.get_current_machine

```{autodoc2-docstring} archivebox.api.v1_machine.get_current_machine
```
````

````{py:function} get_machine(request: django.http.HttpRequest, machine_id: str)
:canonical: archivebox.api.v1_machine.get_machine

```{autodoc2-docstring} archivebox.api.v1_machine.get_machine
```
````

````{py:function} get_binaries(request: django.http.HttpRequest, filters: ninja.Query[archivebox.api.v1_machine.BinaryFilterSchema])
:canonical: archivebox.api.v1_machine.get_binaries

```{autodoc2-docstring} archivebox.api.v1_machine.get_binaries
```
````

````{py:function} get_binary(request: django.http.HttpRequest, binary_id: str)
:canonical: archivebox.api.v1_machine.get_binary

```{autodoc2-docstring} archivebox.api.v1_machine.get_binary
```
````

````{py:function} get_binaries_by_name(request: django.http.HttpRequest, name: str)
:canonical: archivebox.api.v1_machine.get_binaries_by_name

```{autodoc2-docstring} archivebox.api.v1_machine.get_binaries_by_name
```
````
