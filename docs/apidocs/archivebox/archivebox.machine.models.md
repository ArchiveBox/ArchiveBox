# {py:mod}`archivebox.machine.models`

```{py:module} archivebox.machine.models
```

```{autodoc2-docstring} archivebox.machine.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineManager <archivebox.machine.models.MachineManager>`
  - ```{autodoc2-docstring} archivebox.machine.models.MachineManager
    :summary:
    ```
* - {py:obj}`Machine <archivebox.machine.models.Machine>`
  -
* - {py:obj}`NetworkInterfaceManager <archivebox.machine.models.NetworkInterfaceManager>`
  - ```{autodoc2-docstring} archivebox.machine.models.NetworkInterfaceManager
    :summary:
    ```
* - {py:obj}`NetworkInterface <archivebox.machine.models.NetworkInterface>`
  -
* - {py:obj}`BinaryManager <archivebox.machine.models.BinaryManager>`
  - ```{autodoc2-docstring} archivebox.machine.models.BinaryManager
    :summary:
    ```
* - {py:obj}`Binary <archivebox.machine.models.Binary>`
  - ```{autodoc2-docstring} archivebox.machine.models.Binary
    :summary:
    ```
* - {py:obj}`ProcessManager <archivebox.machine.models.ProcessManager>`
  - ```{autodoc2-docstring} archivebox.machine.models.ProcessManager
    :summary:
    ```
* - {py:obj}`Process <archivebox.machine.models.Process>`
  - ```{autodoc2-docstring} archivebox.machine.models.Process
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_current_pid_namespace <archivebox.machine.models.get_current_pid_namespace>`
  - ```{autodoc2-docstring} archivebox.machine.models.get_current_pid_namespace
    :summary:
    ```
* - {py:obj}`_default_exit_code_for_unowned_process <archivebox.machine.models._default_exit_code_for_unowned_process>`
  - ```{autodoc2-docstring} archivebox.machine.models._default_exit_code_for_unowned_process
    :summary:
    ```
* - {py:obj}`_find_existing_binary_for_reference <archivebox.machine.models._find_existing_binary_for_reference>`
  - ```{autodoc2-docstring} archivebox.machine.models._find_existing_binary_for_reference
    :summary:
    ```
* - {py:obj}`_canonical_binary_name <archivebox.machine.models._canonical_binary_name>`
  - ```{autodoc2-docstring} archivebox.machine.models._canonical_binary_name
    :summary:
    ```
* - {py:obj}`_get_process_binary_env_keys <archivebox.machine.models._get_process_binary_env_keys>`
  - ```{autodoc2-docstring} archivebox.machine.models._get_process_binary_env_keys
    :summary:
    ```
* - {py:obj}`_sanitize_machine_config <archivebox.machine.models._sanitize_machine_config>`
  - ```{autodoc2-docstring} archivebox.machine.models._sanitize_machine_config
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_psutil <archivebox.machine.models._psutil>`
  - ```{autodoc2-docstring} archivebox.machine.models._psutil
    :summary:
    ```
* - {py:obj}`_CURRENT_MACHINE <archivebox.machine.models._CURRENT_MACHINE>`
  - ```{autodoc2-docstring} archivebox.machine.models._CURRENT_MACHINE
    :summary:
    ```
* - {py:obj}`_CURRENT_INTERFACE <archivebox.machine.models._CURRENT_INTERFACE>`
  - ```{autodoc2-docstring} archivebox.machine.models._CURRENT_INTERFACE
    :summary:
    ```
* - {py:obj}`_CURRENT_BINARIES <archivebox.machine.models._CURRENT_BINARIES>`
  - ```{autodoc2-docstring} archivebox.machine.models._CURRENT_BINARIES
    :summary:
    ```
* - {py:obj}`_CURRENT_PROCESS <archivebox.machine.models._CURRENT_PROCESS>`
  - ```{autodoc2-docstring} archivebox.machine.models._CURRENT_PROCESS
    :summary:
    ```
* - {py:obj}`MACHINE_RECHECK_INTERVAL <archivebox.machine.models.MACHINE_RECHECK_INTERVAL>`
  - ```{autodoc2-docstring} archivebox.machine.models.MACHINE_RECHECK_INTERVAL
    :summary:
    ```
* - {py:obj}`NETWORK_INTERFACE_RECHECK_INTERVAL <archivebox.machine.models.NETWORK_INTERFACE_RECHECK_INTERVAL>`
  - ```{autodoc2-docstring} archivebox.machine.models.NETWORK_INTERFACE_RECHECK_INTERVAL
    :summary:
    ```
* - {py:obj}`BINARY_RECHECK_INTERVAL <archivebox.machine.models.BINARY_RECHECK_INTERVAL>`
  - ```{autodoc2-docstring} archivebox.machine.models.BINARY_RECHECK_INTERVAL
    :summary:
    ```
* - {py:obj}`PROCESS_RECHECK_INTERVAL <archivebox.machine.models.PROCESS_RECHECK_INTERVAL>`
  - ```{autodoc2-docstring} archivebox.machine.models.PROCESS_RECHECK_INTERVAL
    :summary:
    ```
* - {py:obj}`PID_REUSE_WINDOW <archivebox.machine.models.PID_REUSE_WINDOW>`
  - ```{autodoc2-docstring} archivebox.machine.models.PID_REUSE_WINDOW
    :summary:
    ```
* - {py:obj}`PROCESS_TIMEOUT_GRACE <archivebox.machine.models.PROCESS_TIMEOUT_GRACE>`
  - ```{autodoc2-docstring} archivebox.machine.models.PROCESS_TIMEOUT_GRACE
    :summary:
    ```
* - {py:obj}`START_TIME_TOLERANCE <archivebox.machine.models.START_TIME_TOLERANCE>`
  - ```{autodoc2-docstring} archivebox.machine.models.START_TIME_TOLERANCE
    :summary:
    ```
* - {py:obj}`PROCESS_PID_NAMESPACE_KEY <archivebox.machine.models.PROCESS_PID_NAMESPACE_KEY>`
  - ```{autodoc2-docstring} archivebox.machine.models.PROCESS_PID_NAMESPACE_KEY
    :summary:
    ```
````

### API

````{py:data} _psutil
:canonical: archivebox.machine.models._psutil
:type: typing.Any | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models._psutil
```

````

````{py:data} _CURRENT_MACHINE
:canonical: archivebox.machine.models._CURRENT_MACHINE
:type: archivebox.machine.models.Machine | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models._CURRENT_MACHINE
```

````

````{py:data} _CURRENT_INTERFACE
:canonical: archivebox.machine.models._CURRENT_INTERFACE
:type: archivebox.machine.models.NetworkInterface | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models._CURRENT_INTERFACE
```

````

````{py:data} _CURRENT_BINARIES
:canonical: archivebox.machine.models._CURRENT_BINARIES
:type: dict[str, archivebox.machine.models.Binary]
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models._CURRENT_BINARIES
```

````

````{py:data} _CURRENT_PROCESS
:canonical: archivebox.machine.models._CURRENT_PROCESS
:type: archivebox.machine.models.Process | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models._CURRENT_PROCESS
```

````

````{py:data} MACHINE_RECHECK_INTERVAL
:canonical: archivebox.machine.models.MACHINE_RECHECK_INTERVAL
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.MACHINE_RECHECK_INTERVAL
```

````

````{py:data} NETWORK_INTERFACE_RECHECK_INTERVAL
:canonical: archivebox.machine.models.NETWORK_INTERFACE_RECHECK_INTERVAL
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.NETWORK_INTERFACE_RECHECK_INTERVAL
```

````

````{py:data} BINARY_RECHECK_INTERVAL
:canonical: archivebox.machine.models.BINARY_RECHECK_INTERVAL
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.BINARY_RECHECK_INTERVAL
```

````

````{py:data} PROCESS_RECHECK_INTERVAL
:canonical: archivebox.machine.models.PROCESS_RECHECK_INTERVAL
:value: >
   60

```{autodoc2-docstring} archivebox.machine.models.PROCESS_RECHECK_INTERVAL
```

````

````{py:data} PID_REUSE_WINDOW
:canonical: archivebox.machine.models.PID_REUSE_WINDOW
:value: >
   'timedelta(...)'

```{autodoc2-docstring} archivebox.machine.models.PID_REUSE_WINDOW
```

````

````{py:data} PROCESS_TIMEOUT_GRACE
:canonical: archivebox.machine.models.PROCESS_TIMEOUT_GRACE
:value: >
   'timedelta(...)'

```{autodoc2-docstring} archivebox.machine.models.PROCESS_TIMEOUT_GRACE
```

````

````{py:data} START_TIME_TOLERANCE
:canonical: archivebox.machine.models.START_TIME_TOLERANCE
:value: >
   5.0

```{autodoc2-docstring} archivebox.machine.models.START_TIME_TOLERANCE
```

````

````{py:data} PROCESS_PID_NAMESPACE_KEY
:canonical: archivebox.machine.models.PROCESS_PID_NAMESPACE_KEY
:value: >
   '_ARCHIVEBOX_PID_NAMESPACE'

```{autodoc2-docstring} archivebox.machine.models.PROCESS_PID_NAMESPACE_KEY
```

````

````{py:function} get_current_pid_namespace() -> str
:canonical: archivebox.machine.models.get_current_pid_namespace

```{autodoc2-docstring} archivebox.machine.models.get_current_pid_namespace
```
````

````{py:function} _default_exit_code_for_unowned_process(process_type: str) -> int
:canonical: archivebox.machine.models._default_exit_code_for_unowned_process

```{autodoc2-docstring} archivebox.machine.models._default_exit_code_for_unowned_process
```
````

````{py:function} _find_existing_binary_for_reference(machine: Machine, reference: str) -> Binary | None
:canonical: archivebox.machine.models._find_existing_binary_for_reference

```{autodoc2-docstring} archivebox.machine.models._find_existing_binary_for_reference
```
````

````{py:function} _canonical_binary_name(name: typing.Any) -> str
:canonical: archivebox.machine.models._canonical_binary_name

```{autodoc2-docstring} archivebox.machine.models._canonical_binary_name
```
````

````{py:function} _get_process_binary_env_keys(plugin_name: str, hook_path: str, env: dict[str, typing.Any] | None) -> list[str]
:canonical: archivebox.machine.models._get_process_binary_env_keys

```{autodoc2-docstring} archivebox.machine.models._get_process_binary_env_keys
```
````

````{py:function} _sanitize_machine_config(config: dict[str, typing.Any] | None, *, lib_dir: str | pathlib.Path | None = None) -> dict[str, typing.Any]
:canonical: archivebox.machine.models._sanitize_machine_config

```{autodoc2-docstring} archivebox.machine.models._sanitize_machine_config
```
````

`````{py:class} MachineManager
:canonical: archivebox.machine.models.MachineManager

Bases: {py:obj}`django.db.models.Manager`

```{autodoc2-docstring} archivebox.machine.models.MachineManager
```

````{py:method} current() -> archivebox.machine.models.Machine
:canonical: archivebox.machine.models.MachineManager.current

```{autodoc2-docstring} archivebox.machine.models.MachineManager.current
```

````

`````

``````{py:class} Machine(*args, **kwargs)
:canonical: archivebox.machine.models.Machine

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats`

````{py:attribute} id
:canonical: archivebox.machine.models.Machine.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.id
```

````

````{py:attribute} created_at
:canonical: archivebox.machine.models.Machine.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.machine.models.Machine.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.modified_at
```

````

````{py:attribute} guid
:canonical: archivebox.machine.models.Machine.guid
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.guid
```

````

````{py:attribute} hostname
:canonical: archivebox.machine.models.Machine.hostname
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hostname
```

````

````{py:attribute} hw_in_docker
:canonical: archivebox.machine.models.Machine.hw_in_docker
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hw_in_docker
```

````

````{py:attribute} hw_in_vm
:canonical: archivebox.machine.models.Machine.hw_in_vm
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hw_in_vm
```

````

````{py:attribute} hw_manufacturer
:canonical: archivebox.machine.models.Machine.hw_manufacturer
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hw_manufacturer
```

````

````{py:attribute} hw_product
:canonical: archivebox.machine.models.Machine.hw_product
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hw_product
```

````

````{py:attribute} hw_uuid
:canonical: archivebox.machine.models.Machine.hw_uuid
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.hw_uuid
```

````

````{py:attribute} os_arch
:canonical: archivebox.machine.models.Machine.os_arch
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.os_arch
```

````

````{py:attribute} os_family
:canonical: archivebox.machine.models.Machine.os_family
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.os_family
```

````

````{py:attribute} os_platform
:canonical: archivebox.machine.models.Machine.os_platform
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.os_platform
```

````

````{py:attribute} os_release
:canonical: archivebox.machine.models.Machine.os_release
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.os_release
```

````

````{py:attribute} os_kernel
:canonical: archivebox.machine.models.Machine.os_kernel
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.os_kernel
```

````

````{py:attribute} stats
:canonical: archivebox.machine.models.Machine.stats
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.stats
```

````

````{py:attribute} config
:canonical: archivebox.machine.models.Machine.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.config
```

````

````{py:attribute} num_uses_failed
:canonical: archivebox.machine.models.Machine.num_uses_failed
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.num_uses_failed
```

````

````{py:attribute} num_uses_succeeded
:canonical: archivebox.machine.models.Machine.num_uses_succeeded
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.num_uses_succeeded
```

````

````{py:attribute} objects
:canonical: archivebox.machine.models.Machine.objects
:value: >
   'MachineManager(...)'

```{autodoc2-docstring} archivebox.machine.models.Machine.objects
```

````

````{py:attribute} networkinterface_set
:canonical: archivebox.machine.models.Machine.networkinterface_set
:type: django.db.models.Manager[NetworkInterface]
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Machine.networkinterface_set
```

````

`````{py:class} Meta
:canonical: archivebox.machine.models.Machine.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats.Meta`

````{py:attribute} app_label
:canonical: archivebox.machine.models.Machine.Meta.app_label
:value: >
   'machine'

```{autodoc2-docstring} archivebox.machine.models.Machine.Meta.app_label
```

````

`````

````{py:method} current(refresh: bool = False) -> archivebox.machine.models.Machine
:canonical: archivebox.machine.models.Machine.current
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Machine.current
```

````

````{py:method} _sanitize_config(machine: archivebox.machine.models.Machine) -> archivebox.machine.models.Machine
:canonical: archivebox.machine.models.Machine._sanitize_config
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Machine._sanitize_config
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.machine.models.Machine.to_json

```{autodoc2-docstring} archivebox.machine.models.Machine.to_json
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None)
:canonical: archivebox.machine.models.Machine.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.machine.models.Machine.from_json
```

````

````{py:method} save(*args, **kwargs)
:canonical: archivebox.machine.models.Machine.save

````

``````

`````{py:class} NetworkInterfaceManager
:canonical: archivebox.machine.models.NetworkInterfaceManager

Bases: {py:obj}`django.db.models.Manager`

```{autodoc2-docstring} archivebox.machine.models.NetworkInterfaceManager
```

````{py:method} current() -> archivebox.machine.models.NetworkInterface
:canonical: archivebox.machine.models.NetworkInterfaceManager.current

```{autodoc2-docstring} archivebox.machine.models.NetworkInterfaceManager.current
```

````

`````

``````{py:class} NetworkInterface(*args, **kwargs)
:canonical: archivebox.machine.models.NetworkInterface

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats`

````{py:attribute} id
:canonical: archivebox.machine.models.NetworkInterface.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.id
```

````

````{py:attribute} created_at
:canonical: archivebox.machine.models.NetworkInterface.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.machine.models.NetworkInterface.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.modified_at
```

````

````{py:attribute} machine
:canonical: archivebox.machine.models.NetworkInterface.machine
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.machine
```

````

````{py:attribute} mac_address
:canonical: archivebox.machine.models.NetworkInterface.mac_address
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.mac_address
```

````

````{py:attribute} ip_public
:canonical: archivebox.machine.models.NetworkInterface.ip_public
:value: >
   'GenericIPAddressField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.ip_public
```

````

````{py:attribute} ip_local
:canonical: archivebox.machine.models.NetworkInterface.ip_local
:value: >
   'GenericIPAddressField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.ip_local
```

````

````{py:attribute} dns_server
:canonical: archivebox.machine.models.NetworkInterface.dns_server
:value: >
   'GenericIPAddressField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.dns_server
```

````

````{py:attribute} hostname
:canonical: archivebox.machine.models.NetworkInterface.hostname
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.hostname
```

````

````{py:attribute} iface
:canonical: archivebox.machine.models.NetworkInterface.iface
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.iface
```

````

````{py:attribute} isp
:canonical: archivebox.machine.models.NetworkInterface.isp
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.isp
```

````

````{py:attribute} city
:canonical: archivebox.machine.models.NetworkInterface.city
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.city
```

````

````{py:attribute} region
:canonical: archivebox.machine.models.NetworkInterface.region
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.region
```

````

````{py:attribute} country
:canonical: archivebox.machine.models.NetworkInterface.country
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.country
```

````

````{py:attribute} objects
:canonical: archivebox.machine.models.NetworkInterface.objects
:value: >
   'NetworkInterfaceManager(...)'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.objects
```

````

````{py:attribute} machine_id
:canonical: archivebox.machine.models.NetworkInterface.machine_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.machine_id
```

````

`````{py:class} Meta
:canonical: archivebox.machine.models.NetworkInterface.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats.Meta`

````{py:attribute} app_label
:canonical: archivebox.machine.models.NetworkInterface.Meta.app_label
:value: >
   'machine'

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.Meta.app_label
```

````

````{py:attribute} unique_together
:canonical: archivebox.machine.models.NetworkInterface.Meta.unique_together
:value: >
   (('machine', 'ip_public', 'ip_local', 'dns_server'),)

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.Meta.unique_together
```

````

````{py:attribute} constraints
:canonical: archivebox.machine.models.NetworkInterface.Meta.constraints
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.Meta.constraints
```

````

`````

````{py:method} current(refresh: bool = False) -> archivebox.machine.models.NetworkInterface
:canonical: archivebox.machine.models.NetworkInterface.current
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.NetworkInterface.current
```

````

``````

`````{py:class} BinaryManager
:canonical: archivebox.machine.models.BinaryManager

Bases: {py:obj}`django.db.models.Manager`

```{autodoc2-docstring} archivebox.machine.models.BinaryManager
```

````{py:method} get_from_db_or_cache(name: str, abspath: str = '', version: str = '', sha256: str = '', binprovider: str = 'env') -> archivebox.machine.models.Binary
:canonical: archivebox.machine.models.BinaryManager.get_from_db_or_cache

```{autodoc2-docstring} archivebox.machine.models.BinaryManager.get_from_db_or_cache
```

````

````{py:method} get_valid_binary(name: str, machine: archivebox.machine.models.Machine | None = None) -> archivebox.machine.models.Binary | None
:canonical: archivebox.machine.models.BinaryManager.get_valid_binary

```{autodoc2-docstring} archivebox.machine.models.BinaryManager.get_valid_binary
```

````

`````

``````{py:class} Binary(*args, **kwargs)
:canonical: archivebox.machine.models.Binary

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats`, {py:obj}`archivebox.workers.models.ModelWithQueue`

```{autodoc2-docstring} archivebox.machine.models.Binary
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.machine.models.Binary.__init__
```

`````{py:class} StatusChoices()
:canonical: archivebox.machine.models.Binary.StatusChoices

Bases: {py:obj}`django.db.models.TextChoices`

````{py:attribute} QUEUED
:canonical: archivebox.machine.models.Binary.StatusChoices.QUEUED
:value: >
   ('queued', 'Queued')

```{autodoc2-docstring} archivebox.machine.models.Binary.StatusChoices.QUEUED
```

````

````{py:attribute} INSTALLED
:canonical: archivebox.machine.models.Binary.StatusChoices.INSTALLED
:value: >
   ('installed', 'Installed')

```{autodoc2-docstring} archivebox.machine.models.Binary.StatusChoices.INSTALLED
```

````

`````

````{py:attribute} id
:canonical: archivebox.machine.models.Binary.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.id
```

````

````{py:attribute} created_at
:canonical: archivebox.machine.models.Binary.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.machine.models.Binary.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.modified_at
```

````

````{py:attribute} machine
:canonical: archivebox.machine.models.Binary.machine
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.machine
```

````

````{py:attribute} name
:canonical: archivebox.machine.models.Binary.name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.name
```

````

````{py:attribute} binproviders
:canonical: archivebox.machine.models.Binary.binproviders
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.binproviders
```

````

````{py:attribute} overrides
:canonical: archivebox.machine.models.Binary.overrides
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.overrides
```

````

````{py:attribute} binprovider
:canonical: archivebox.machine.models.Binary.binprovider
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.binprovider
```

````

````{py:attribute} abspath
:canonical: archivebox.machine.models.Binary.abspath
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.abspath
```

````

````{py:attribute} version
:canonical: archivebox.machine.models.Binary.version
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.version
```

````

````{py:attribute} sha256
:canonical: archivebox.machine.models.Binary.sha256
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.sha256
```

````

````{py:attribute} status
:canonical: archivebox.machine.models.Binary.status
:value: >
   'StatusField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.machine.models.Binary.retry_at
:value: >
   'RetryAtField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.retry_at
```

````

````{py:attribute} num_uses_failed
:canonical: archivebox.machine.models.Binary.num_uses_failed
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.num_uses_failed
```

````

````{py:attribute} num_uses_succeeded
:canonical: archivebox.machine.models.Binary.num_uses_succeeded
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.num_uses_succeeded
```

````

````{py:attribute} machine_id
:canonical: archivebox.machine.models.Binary.machine_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Binary.machine_id
```

````

````{py:attribute} INITIAL_STATE
:canonical: archivebox.machine.models.Binary.INITIAL_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Binary.INITIAL_STATE
```

````

````{py:attribute} ACTIVE_STATE
:canonical: archivebox.machine.models.Binary.ACTIVE_STATE
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Binary.ACTIVE_STATE
```

````

````{py:attribute} FINAL_STATES
:canonical: archivebox.machine.models.Binary.FINAL_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.machine.models.Binary.FINAL_STATES
```

````

````{py:attribute} FINAL_OR_ACTIVE_STATES
:canonical: archivebox.machine.models.Binary.FINAL_OR_ACTIVE_STATES
:value: >
   ()

```{autodoc2-docstring} archivebox.machine.models.Binary.FINAL_OR_ACTIVE_STATES
```

````

````{py:attribute} active_state
:canonical: archivebox.machine.models.Binary.active_state
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Binary.active_state
```

````

````{py:attribute} warn_on_save_outside_runner
:canonical: archivebox.machine.models.Binary.warn_on_save_outside_runner
:value: >
   False

```{autodoc2-docstring} archivebox.machine.models.Binary.warn_on_save_outside_runner
```

````

````{py:attribute} objects
:canonical: archivebox.machine.models.Binary.objects
:value: >
   'BinaryManager(...)'

```{autodoc2-docstring} archivebox.machine.models.Binary.objects
```

````

`````{py:class} Meta
:canonical: archivebox.machine.models.Binary.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithHealthStats.Meta`, {py:obj}`archivebox.workers.models.ModelWithQueue.Meta`

````{py:attribute} app_label
:canonical: archivebox.machine.models.Binary.Meta.app_label
:value: >
   'machine'

```{autodoc2-docstring} archivebox.machine.models.Binary.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.machine.models.Binary.Meta.verbose_name
:value: >
   'Binary'

```{autodoc2-docstring} archivebox.machine.models.Binary.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.machine.models.Binary.Meta.verbose_name_plural
:value: >
   'Binaries'

```{autodoc2-docstring} archivebox.machine.models.Binary.Meta.verbose_name_plural
```

````

````{py:attribute} unique_together
:canonical: archivebox.machine.models.Binary.Meta.unique_together
:value: >
   (('machine', 'name', 'abspath', 'version', 'sha256'),)

```{autodoc2-docstring} archivebox.machine.models.Binary.Meta.unique_together
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.machine.models.Binary.__str__

````

````{py:property} is_valid
:canonical: archivebox.machine.models.Binary.is_valid
:type: bool

```{autodoc2-docstring} archivebox.machine.models.Binary.is_valid
```

````

````{py:property} can_install
:canonical: archivebox.machine.models.Binary.can_install
:type: bool

```{autodoc2-docstring} archivebox.machine.models.Binary.can_install
```

````

````{py:method} binary_info() -> dict
:canonical: archivebox.machine.models.Binary.binary_info

```{autodoc2-docstring} archivebox.machine.models.Binary.binary_info
```

````

````{py:property} output_dir
:canonical: archivebox.machine.models.Binary.output_dir
:type: pathlib.Path

```{autodoc2-docstring} archivebox.machine.models.Binary.output_dir
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.machine.models.Binary.to_json

```{autodoc2-docstring} archivebox.machine.models.Binary.to_json
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None)
:canonical: archivebox.machine.models.Binary.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.machine.models.Binary.from_json
```

````

````{py:method} _allowed_binproviders() -> set[str] | None
:canonical: archivebox.machine.models.Binary._allowed_binproviders

```{autodoc2-docstring} archivebox.machine.models.Binary._allowed_binproviders
```

````

````{py:method} run()
:canonical: archivebox.machine.models.Binary.run

```{autodoc2-docstring} archivebox.machine.models.Binary.run
```

````

````{py:method} install() -> bool
:canonical: archivebox.machine.models.Binary.install

```{autodoc2-docstring} archivebox.machine.models.Binary.install
```

````

````{py:method} advance_lifecycle() -> bool
:canonical: archivebox.machine.models.Binary.advance_lifecycle

```{autodoc2-docstring} archivebox.machine.models.Binary.advance_lifecycle
```

````

````{py:method} install_claimed(*, lock_seconds: int = 600) -> bool
:canonical: archivebox.machine.models.Binary.install_claimed

```{autodoc2-docstring} archivebox.machine.models.Binary.install_claimed
```

````

````{py:method} cleanup()
:canonical: archivebox.machine.models.Binary.cleanup

```{autodoc2-docstring} archivebox.machine.models.Binary.cleanup
```

````

````{py:method} symlink_to_lib_bin(lib_bin_dir: str | pathlib.Path) -> pathlib.Path | None
:canonical: archivebox.machine.models.Binary.symlink_to_lib_bin

```{autodoc2-docstring} archivebox.machine.models.Binary.symlink_to_lib_bin
```

````

````{py:method} symlink_to_lib_bin_after_commit(lib_bin_dir: str | pathlib.Path) -> None
:canonical: archivebox.machine.models.Binary.symlink_to_lib_bin_after_commit

```{autodoc2-docstring} archivebox.machine.models.Binary.symlink_to_lib_bin_after_commit
```

````

``````

`````{py:class} ProcessManager
:canonical: archivebox.machine.models.ProcessManager

Bases: {py:obj}`django.db.models.Manager`

```{autodoc2-docstring} archivebox.machine.models.ProcessManager
```

````{py:method} current() -> archivebox.machine.models.Process
:canonical: archivebox.machine.models.ProcessManager.current

```{autodoc2-docstring} archivebox.machine.models.ProcessManager.current
```

````

````{py:method} get_by_pid(pid: int, machine: archivebox.machine.models.Machine | None = None) -> archivebox.machine.models.Process | None
:canonical: archivebox.machine.models.ProcessManager.get_by_pid

```{autodoc2-docstring} archivebox.machine.models.ProcessManager.get_by_pid
```

````

````{py:method} create_for_archiveresult(archiveresult, **kwargs)
:canonical: archivebox.machine.models.ProcessManager.create_for_archiveresult

```{autodoc2-docstring} archivebox.machine.models.ProcessManager.create_for_archiveresult
```

````

`````

``````{py:class} Process(*args, **kwargs)
:canonical: archivebox.machine.models.Process

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter`, {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.machine.models.Process
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.machine.models.Process.__init__
```

`````{py:class} StatusChoices()
:canonical: archivebox.machine.models.Process.StatusChoices

Bases: {py:obj}`django.db.models.TextChoices`

````{py:attribute} QUEUED
:canonical: archivebox.machine.models.Process.StatusChoices.QUEUED
:value: >
   ('queued', 'Queued')

```{autodoc2-docstring} archivebox.machine.models.Process.StatusChoices.QUEUED
```

````

````{py:attribute} RUNNING
:canonical: archivebox.machine.models.Process.StatusChoices.RUNNING
:value: >
   ('running', 'Running')

```{autodoc2-docstring} archivebox.machine.models.Process.StatusChoices.RUNNING
```

````

````{py:attribute} EXITED
:canonical: archivebox.machine.models.Process.StatusChoices.EXITED
:value: >
   ('exited', 'Exited')

```{autodoc2-docstring} archivebox.machine.models.Process.StatusChoices.EXITED
```

````

`````

`````{py:class} TypeChoices()
:canonical: archivebox.machine.models.Process.TypeChoices

Bases: {py:obj}`django.db.models.TextChoices`

````{py:attribute} SUPERVISORD
:canonical: archivebox.machine.models.Process.TypeChoices.SUPERVISORD
:value: >
   ('supervisord', 'Supervisord')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.SUPERVISORD
```

````

````{py:attribute} ORCHESTRATOR
:canonical: archivebox.machine.models.Process.TypeChoices.ORCHESTRATOR
:value: >
   ('orchestrator', 'Orchestrator')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.ORCHESTRATOR
```

````

````{py:attribute} SERVER
:canonical: archivebox.machine.models.Process.TypeChoices.SERVER
:value: >
   ('server', 'Server')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.SERVER
```

````

````{py:attribute} UPDATE
:canonical: archivebox.machine.models.Process.TypeChoices.UPDATE
:value: >
   ('update', 'Update')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.UPDATE
```

````

````{py:attribute} ADD
:canonical: archivebox.machine.models.Process.TypeChoices.ADD
:value: >
   ('add', 'Add')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.ADD
```

````

````{py:attribute} SEARCH
:canonical: archivebox.machine.models.Process.TypeChoices.SEARCH
:value: >
   ('search', 'Search')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.SEARCH
```

````

````{py:attribute} WORKER
:canonical: archivebox.machine.models.Process.TypeChoices.WORKER
:value: >
   ('worker', 'Worker')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.WORKER
```

````

````{py:attribute} CLI
:canonical: archivebox.machine.models.Process.TypeChoices.CLI
:value: >
   ('cli', 'CLI')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.CLI
```

````

````{py:attribute} HOOK
:canonical: archivebox.machine.models.Process.TypeChoices.HOOK
:value: >
   ('hook', 'Hook')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.HOOK
```

````

````{py:attribute} BINARY
:canonical: archivebox.machine.models.Process.TypeChoices.BINARY
:value: >
   ('binary', 'Binary')

```{autodoc2-docstring} archivebox.machine.models.Process.TypeChoices.BINARY
```

````

`````

````{py:attribute} id
:canonical: archivebox.machine.models.Process.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.id
```

````

````{py:attribute} created_at
:canonical: archivebox.machine.models.Process.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.machine.models.Process.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.modified_at
```

````

````{py:attribute} machine
:canonical: archivebox.machine.models.Process.machine
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.machine
```

````

````{py:attribute} parent
:canonical: archivebox.machine.models.Process.parent
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.parent
```

````

````{py:attribute} process_type
:canonical: archivebox.machine.models.Process.process_type
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.process_type
```

````

````{py:attribute} worker_type
:canonical: archivebox.machine.models.Process.worker_type
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.worker_type
```

````

````{py:attribute} pwd
:canonical: archivebox.machine.models.Process.pwd
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.pwd
```

````

````{py:attribute} cmd
:canonical: archivebox.machine.models.Process.cmd
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.cmd
```

````

````{py:attribute} env
:canonical: archivebox.machine.models.Process.env
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.env
```

````

````{py:attribute} timeout
:canonical: archivebox.machine.models.Process.timeout
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.timeout
```

````

````{py:attribute} pid
:canonical: archivebox.machine.models.Process.pid
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.pid
```

````

````{py:attribute} exit_code
:canonical: archivebox.machine.models.Process.exit_code
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.exit_code
```

````

````{py:attribute} stdout
:canonical: archivebox.machine.models.Process.stdout
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.stdout
```

````

````{py:attribute} stderr
:canonical: archivebox.machine.models.Process.stderr
:value: >
   'TextField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.stderr
```

````

````{py:attribute} started_at
:canonical: archivebox.machine.models.Process.started_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.started_at
```

````

````{py:attribute} ended_at
:canonical: archivebox.machine.models.Process.ended_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.ended_at
```

````

````{py:attribute} binary
:canonical: archivebox.machine.models.Process.binary
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.binary
```

````

````{py:attribute} iface
:canonical: archivebox.machine.models.Process.iface
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.iface
```

````

````{py:attribute} url
:canonical: archivebox.machine.models.Process.url
:value: >
   'URLField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.url
```

````

````{py:attribute} status
:canonical: archivebox.machine.models.Process.status
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.machine.models.Process.retry_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.retry_at
```

````

````{py:attribute} machine_id
:canonical: archivebox.machine.models.Process.machine_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.machine_id
```

````

````{py:attribute} parent_id
:canonical: archivebox.machine.models.Process.parent_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.parent_id
```

````

````{py:attribute} binary_id
:canonical: archivebox.machine.models.Process.binary_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.binary_id
```

````

````{py:attribute} children
:canonical: archivebox.machine.models.Process.children
:type: django.db.models.Manager[archivebox.machine.models.Process]
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.children
```

````

````{py:attribute} archiveresult
:canonical: archivebox.machine.models.Process.archiveresult
:type: archivebox.core.models.ArchiveResult
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.archiveresult
```

````

````{py:attribute} delete_after_final_statuses
:canonical: archivebox.machine.models.Process.delete_after_final_statuses
:value: >
   ()

```{autodoc2-docstring} archivebox.machine.models.Process.delete_after_final_statuses
```

````

````{py:attribute} objects
:canonical: archivebox.machine.models.Process.objects
:value: >
   'ProcessManager(...)'

```{autodoc2-docstring} archivebox.machine.models.Process.objects
```

````

`````{py:class} Meta
:canonical: archivebox.machine.models.Process.Meta

Bases: {py:obj}`archivebox.base_models.models.ModelWithDeleteAfter.Meta`

````{py:attribute} app_label
:canonical: archivebox.machine.models.Process.Meta.app_label
:value: >
   'machine'

```{autodoc2-docstring} archivebox.machine.models.Process.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.machine.models.Process.Meta.verbose_name
:value: >
   'Process'

```{autodoc2-docstring} archivebox.machine.models.Process.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.machine.models.Process.Meta.verbose_name_plural
:value: >
   'Processes'

```{autodoc2-docstring} archivebox.machine.models.Process.Meta.verbose_name_plural
```

````

````{py:attribute} indexes
:canonical: archivebox.machine.models.Process.Meta.indexes
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.Meta.indexes
```

````

````{py:attribute} constraints
:canonical: archivebox.machine.models.Process.Meta.constraints
:value: >
   None

```{autodoc2-docstring} archivebox.machine.models.Process.Meta.constraints
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.machine.models.Process.__str__

````

````{py:method} get_delete_after_config_value()
:canonical: archivebox.machine.models.Process.get_delete_after_config_value

```{autodoc2-docstring} archivebox.machine.models.Process.get_delete_after_config_value
```

````

````{py:method} missing_delete_at_candidates()
:canonical: archivebox.machine.models.Process.missing_delete_at_candidates
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.missing_delete_at_candidates
```

````

````{py:property} cmd_version
:canonical: archivebox.machine.models.Process.cmd_version
:type: str

```{autodoc2-docstring} archivebox.machine.models.Process.cmd_version
```

````

````{py:property} bin_abspath
:canonical: archivebox.machine.models.Process.bin_abspath
:type: str

```{autodoc2-docstring} archivebox.machine.models.Process.bin_abspath
```

````

````{py:property} plugin
:canonical: archivebox.machine.models.Process.plugin
:type: str

```{autodoc2-docstring} archivebox.machine.models.Process.plugin
```

````

````{py:property} hook_name
:canonical: archivebox.machine.models.Process.hook_name
:type: str

```{autodoc2-docstring} archivebox.machine.models.Process.hook_name
```

````

````{py:method} to_json() -> dict
:canonical: archivebox.machine.models.Process.to_json

```{autodoc2-docstring} archivebox.machine.models.Process.to_json
```

````

````{py:method} hydrate_binary_from_context(*, plugin_name: str = '', hook_path: str = '') -> archivebox.machine.models.Binary | None
:canonical: archivebox.machine.models.Process.hydrate_binary_from_context

```{autodoc2-docstring} archivebox.machine.models.Process.hydrate_binary_from_context
```

````

````{py:method} parse_records_from_text(text: str) -> list[dict]
:canonical: archivebox.machine.models.Process.parse_records_from_text
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.parse_records_from_text
```

````

````{py:method} get_records() -> list[dict]
:canonical: archivebox.machine.models.Process.get_records

```{autodoc2-docstring} archivebox.machine.models.Process.get_records
```

````

````{py:method} from_json(record: dict[str, typing.Any], overrides: dict[str, typing.Any] | None = None)
:canonical: archivebox.machine.models.Process.from_json
:staticmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.from_json
```

````

````{py:method} safe_update(update_fields: dict[str, typing.Any], *, refresh: bool = True, extra_filter: dict[str, typing.Any] | None = None) -> bool
:canonical: archivebox.machine.models.Process.safe_update

```{autodoc2-docstring} archivebox.machine.models.Process.safe_update
```

````

````{py:method} update_and_requeue(**kwargs) -> bool
:canonical: archivebox.machine.models.Process.update_and_requeue

```{autodoc2-docstring} archivebox.machine.models.Process.update_and_requeue
```

````

````{py:method} mark_running(*, process_type: str | None = None, pwd: str | pathlib.Path | None = None, url: str | None = None, worker_type: str = '', timeout: int | None = None) -> None
:canonical: archivebox.machine.models.Process.mark_running

```{autodoc2-docstring} archivebox.machine.models.Process.mark_running
```

````

````{py:method} heartbeat() -> None
:canonical: archivebox.machine.models.Process.heartbeat

```{autodoc2-docstring} archivebox.machine.models.Process.heartbeat
```

````

````{py:method} mark_exited(*, exit_code: int = 0) -> None
:canonical: archivebox.machine.models.Process.mark_exited

```{autodoc2-docstring} archivebox.machine.models.Process.mark_exited
```

````

````{py:method} current() -> archivebox.machine.models.Process
:canonical: archivebox.machine.models.Process.current
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.current
```

````

````{py:method} _find_parent_process(machine: archivebox.machine.models.Machine | None = None) -> archivebox.machine.models.Process | None
:canonical: archivebox.machine.models.Process._find_parent_process
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process._find_parent_process
```

````

````{py:method} _detect_process_type() -> str
:canonical: archivebox.machine.models.Process._detect_process_type
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process._detect_process_type
```

````

````{py:method} cleanup_stale_running(machine: archivebox.machine.models.Machine | None = None) -> int
:canonical: archivebox.machine.models.Process.cleanup_stale_running
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.cleanup_stale_running
```

````

````{py:property} root
:canonical: archivebox.machine.models.Process.root
:type: archivebox.machine.models.Process

```{autodoc2-docstring} archivebox.machine.models.Process.root
```

````

````{py:property} ancestors
:canonical: archivebox.machine.models.Process.ancestors
:type: list[archivebox.machine.models.Process]

```{autodoc2-docstring} archivebox.machine.models.Process.ancestors
```

````

````{py:property} depth
:canonical: archivebox.machine.models.Process.depth
:type: int

```{autodoc2-docstring} archivebox.machine.models.Process.depth
```

````

````{py:method} get_descendants(include_self: bool = False)
:canonical: archivebox.machine.models.Process.get_descendants

```{autodoc2-docstring} archivebox.machine.models.Process.get_descendants
```

````

````{py:property} shares_pid_namespace
:canonical: archivebox.machine.models.Process.shares_pid_namespace
:type: bool

```{autodoc2-docstring} archivebox.machine.models.Process.shares_pid_namespace
```

````

````{py:property} proc
:canonical: archivebox.machine.models.Process.proc
:type: psutil.Process | None

```{autodoc2-docstring} archivebox.machine.models.Process.proc
```

````

````{py:property} is_running
:canonical: archivebox.machine.models.Process.is_running
:type: bool

```{autodoc2-docstring} archivebox.machine.models.Process.is_running
```

````

````{py:method} is_alive() -> bool
:canonical: archivebox.machine.models.Process.is_alive

```{autodoc2-docstring} archivebox.machine.models.Process.is_alive
```

````

````{py:method} get_memory_info() -> dict | None
:canonical: archivebox.machine.models.Process.get_memory_info

```{autodoc2-docstring} archivebox.machine.models.Process.get_memory_info
```

````

````{py:method} get_cpu_percent() -> float | None
:canonical: archivebox.machine.models.Process.get_cpu_percent

```{autodoc2-docstring} archivebox.machine.models.Process.get_cpu_percent
```

````

````{py:method} get_children_pids() -> list[int]
:canonical: archivebox.machine.models.Process.get_children_pids

```{autodoc2-docstring} archivebox.machine.models.Process.get_children_pids
```

````

````{py:property} stdout_file
:canonical: archivebox.machine.models.Process.stdout_file
:type: pathlib.Path | None

```{autodoc2-docstring} archivebox.machine.models.Process.stdout_file
```

````

````{py:property} stderr_file
:canonical: archivebox.machine.models.Process.stderr_file
:type: pathlib.Path | None

```{autodoc2-docstring} archivebox.machine.models.Process.stderr_file
```

````

````{py:property} hook_script_name
:canonical: archivebox.machine.models.Process.hook_script_name
:type: str | None

```{autodoc2-docstring} archivebox.machine.models.Process.hook_script_name
```

````

````{py:property} runtime_dir
:canonical: archivebox.machine.models.Process.runtime_dir
:type: pathlib.Path | None

```{autodoc2-docstring} archivebox.machine.models.Process.runtime_dir
```

````

````{py:method} tail_stdout(lines: int = 50, follow: bool = False)
:canonical: archivebox.machine.models.Process.tail_stdout

```{autodoc2-docstring} archivebox.machine.models.Process.tail_stdout
```

````

````{py:method} tail_stderr(lines: int = 50, follow: bool = False)
:canonical: archivebox.machine.models.Process.tail_stderr

```{autodoc2-docstring} archivebox.machine.models.Process.tail_stderr
```

````

````{py:method} pipe_stdout(lines: int = 10, follow: bool = True)
:canonical: archivebox.machine.models.Process.pipe_stdout

```{autodoc2-docstring} archivebox.machine.models.Process.pipe_stdout
```

````

````{py:method} pipe_stderr(lines: int = 10, follow: bool = True)
:canonical: archivebox.machine.models.Process.pipe_stderr

```{autodoc2-docstring} archivebox.machine.models.Process.pipe_stderr
```

````

````{py:method} ensure_log_files() -> None
:canonical: archivebox.machine.models.Process.ensure_log_files

```{autodoc2-docstring} archivebox.machine.models.Process.ensure_log_files
```

````

````{py:method} _build_env() -> dict
:canonical: archivebox.machine.models.Process._build_env

```{autodoc2-docstring} archivebox.machine.models.Process._build_env
```

````

````{py:method} launch(background: bool = False, cwd: str | None = None) -> archivebox.machine.models.Process
:canonical: archivebox.machine.models.Process.launch

```{autodoc2-docstring} archivebox.machine.models.Process.launch
```

````

````{py:method} kill(signal_num: int = 15) -> bool
:canonical: archivebox.machine.models.Process.kill

```{autodoc2-docstring} archivebox.machine.models.Process.kill
```

````

````{py:method} poll() -> int | None
:canonical: archivebox.machine.models.Process.poll

```{autodoc2-docstring} archivebox.machine.models.Process.poll
```

````

````{py:method} wait(timeout: int | None = None) -> int
:canonical: archivebox.machine.models.Process.wait

```{autodoc2-docstring} archivebox.machine.models.Process.wait
```

````

````{py:method} terminate(graceful_timeout: float = 5.0) -> bool
:canonical: archivebox.machine.models.Process.terminate

```{autodoc2-docstring} archivebox.machine.models.Process.terminate
```

````

````{py:method} kill_tree(graceful_timeout: float = 2.0) -> int
:canonical: archivebox.machine.models.Process.kill_tree

```{autodoc2-docstring} archivebox.machine.models.Process.kill_tree
```

````

````{py:method} kill_children_db() -> int
:canonical: archivebox.machine.models.Process.kill_children_db

```{autodoc2-docstring} archivebox.machine.models.Process.kill_children_db
```

````

````{py:method} get_running(process_type: str | None = None, machine: archivebox.machine.models.Machine | None = None) -> django.db.models.QuerySet[archivebox.machine.models.Process]
:canonical: archivebox.machine.models.Process.get_running
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.get_running
```

````

````{py:method} get_running_count(process_type: str | None = None, machine: archivebox.machine.models.Machine | None = None) -> int
:canonical: archivebox.machine.models.Process.get_running_count
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.get_running_count
```

````

````{py:method} stop_all(process_type: str | None = None, machine: archivebox.machine.models.Machine | None = None, graceful: bool = True) -> int
:canonical: archivebox.machine.models.Process.stop_all
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.stop_all
```

````

````{py:method} get_next_worker_id(process_type: str = 'worker', machine: archivebox.machine.models.Machine | None = None) -> int
:canonical: archivebox.machine.models.Process.get_next_worker_id
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.get_next_worker_id
```

````

````{py:method} cleanup_orphaned_chrome() -> int
:canonical: archivebox.machine.models.Process.cleanup_orphaned_chrome
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.cleanup_orphaned_chrome
```

````

````{py:method} cleanup_orphaned_workers() -> int
:canonical: archivebox.machine.models.Process.cleanup_orphaned_workers
:classmethod:

```{autodoc2-docstring} archivebox.machine.models.Process.cleanup_orphaned_workers
```

````

``````
