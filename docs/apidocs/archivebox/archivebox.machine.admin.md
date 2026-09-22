# {py:mod}`archivebox.machine.admin`

```{py:module} archivebox.machine.admin
```

```{autodoc2-docstring} archivebox.machine.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineAdmin <archivebox.machine.admin.MachineAdmin>`
  -
* - {py:obj}`NetworkInterfaceAdmin <archivebox.machine.admin.NetworkInterfaceAdmin>`
  -
* - {py:obj}`BinaryAdmin <archivebox.machine.admin.BinaryAdmin>`
  -
* - {py:obj}`ProcessAdmin <archivebox.machine.admin.ProcessAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_render_copy_block <archivebox.machine.admin._render_copy_block>`
  - ```{autodoc2-docstring} archivebox.machine.admin._render_copy_block
    :summary:
    ```
* - {py:obj}`_format_process_duration_seconds <archivebox.machine.admin._format_process_duration_seconds>`
  - ```{autodoc2-docstring} archivebox.machine.admin._format_process_duration_seconds
    :summary:
    ```
* - {py:obj}`register_admin <archivebox.machine.admin.register_admin>`
  - ```{autodoc2-docstring} archivebox.machine.admin.register_admin
    :summary:
    ```
````

### API

````{py:function} _render_copy_block(text: str, *, multiline: bool = False)
:canonical: archivebox.machine.admin._render_copy_block

```{autodoc2-docstring} archivebox.machine.admin._render_copy_block
```
````

````{py:function} _format_process_duration_seconds(started_at, ended_at) -> str
:canonical: archivebox.machine.admin._format_process_duration_seconds

```{autodoc2-docstring} archivebox.machine.admin._format_process_duration_seconds
```
````

`````{py:class} MachineAdmin(model, admin_site)
:canonical: archivebox.machine.admin.MachineAdmin

Bases: {py:obj}`archivebox.base_models.admin.ConfigEditorMixin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.machine.admin.MachineAdmin.list_display
:value: >
   ('id_display', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manuf...

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.machine.admin.MachineAdmin.sort_fields
:value: >
   ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer'...

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.machine.admin.MachineAdmin.readonly_fields
:value: >
   ('guid', 'created_at', 'modified_at', 'ips')

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.machine.admin.MachineAdmin.fieldsets
:value: >
   (('Identity',), ('Hardware',), ('Operating System',), ('Statistics',), ('Configuration',), ('Timesta...

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.machine.admin.MachineAdmin.list_filter
:value: >
   ('hw_in_docker', 'hw_in_vm', 'os_arch', 'os_family', 'os_platform')

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.machine.admin.MachineAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.machine.admin.MachineAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.machine.admin.MachineAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.actions
```

````

````{py:method} ips(machine)
:canonical: archivebox.machine.admin.MachineAdmin.ips

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.ips
```

````

````{py:method} health_display(obj)
:canonical: archivebox.machine.admin.MachineAdmin.health_display

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.health_display
```

````

````{py:method} id_display(machine)
:canonical: archivebox.machine.admin.MachineAdmin.id_display

```{autodoc2-docstring} archivebox.machine.admin.MachineAdmin.id_display
```

````

`````

`````{py:class} NetworkInterfaceAdmin(model, admin_site)
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.list_display
:value: >
   ('id', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', ...

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.sort_fields
:value: >
   ('id', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', ...

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.sort_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.search_fields
:value: >
   ('id', 'machine__id', 'iface', 'ip_public', 'ip_local', 'mac_address', 'dns_server', 'hostname', 'is...

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.readonly_fields
:value: >
   ('machine', 'created_at', 'modified_at', 'mac_address', 'ip_public', 'ip_local', 'dns_server')

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.fieldsets
:value: >
   (('Machine',), ('Network',), ('Location',), ('Usage',), ('Timestamps',))

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.list_filter
:value: >
   ('isp', 'country', 'region')

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.actions
```

````

````{py:method} machine_info(iface)
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.machine_info

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.machine_info
```

````

````{py:method} health_display(obj)
:canonical: archivebox.machine.admin.NetworkInterfaceAdmin.health_display

```{autodoc2-docstring} archivebox.machine.admin.NetworkInterfaceAdmin.health_display
```

````

`````

`````{py:class} BinaryAdmin(model, admin_site)
:canonical: archivebox.machine.admin.BinaryAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.machine.admin.BinaryAdmin.list_display
:value: >
   ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'status'...

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.machine.admin.BinaryAdmin.sort_fields
:value: >
   ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'status'...

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.sort_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.machine.admin.BinaryAdmin.search_fields
:value: >
   ('id', 'machine__id', 'name', 'binprovider', 'version', 'abspath', 'sha256')

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.machine.admin.BinaryAdmin.readonly_fields
:value: >
   ('created_at', 'modified_at', 'output_dir')

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.machine.admin.BinaryAdmin.fieldsets
:value: >
   (('Binary Info',), ('Location',), ('Version',), ('State',), ('Usage',), ('Timestamps',))

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.machine.admin.BinaryAdmin.list_filter
:value: >
   ('name', 'binprovider', 'status', 'machine_id')

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.machine.admin.BinaryAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.machine.admin.BinaryAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.machine.admin.BinaryAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.actions
```

````

````{py:method} machine_info(binary)
:canonical: archivebox.machine.admin.BinaryAdmin.machine_info

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.machine_info
```

````

````{py:method} health_display(obj)
:canonical: archivebox.machine.admin.BinaryAdmin.health_display

```{autodoc2-docstring} archivebox.machine.admin.BinaryAdmin.health_display
```

````

`````

`````{py:class} ProcessAdmin(model, admin_site)
:canonical: archivebox.machine.admin.ProcessAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.machine.admin.ProcessAdmin.list_display
:value: >
   ('id', 'created_at', 'machine_info', 'archiveresult_link', 'snapshot_link', 'crawl_link', 'cmd_str',...

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.machine.admin.ProcessAdmin.sort_fields
:value: >
   ('id', 'created_at', 'machine_info', 'archiveresult_link', 'snapshot_link', 'crawl_link', 'cmd_str',...

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.sort_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.machine.admin.ProcessAdmin.search_fields
:value: >
   ('id', 'machine__id', 'binary__name', 'cmd', 'pwd', 'stdout', 'stderr')

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.machine.admin.ProcessAdmin.readonly_fields
:value: >
   ('created_at', 'modified_at', 'machine', 'binary_link', 'iface_link', 'archiveresult_link', 'snapsho...

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.machine.admin.ProcessAdmin.fieldsets
:value: >
   (('Process Info',), ('Command',), ('Execution',), ('Timing',), ('Output',), ('Timestamps',))

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.machine.admin.ProcessAdmin.list_filter
:value: >
   ('status', 'exit_code', 'machine_id')

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.machine.admin.ProcessAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.machine.admin.ProcessAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.machine.admin.ProcessAdmin.actions
:value: >
   ['kill_processes', 'delete_selected']

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.actions
```

````

````{py:attribute} change_actions
:canonical: archivebox.machine.admin.ProcessAdmin.change_actions
:value: >
   ['kill_process']

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.change_actions
```

````

````{py:method} get_queryset(request)
:canonical: archivebox.machine.admin.ProcessAdmin.get_queryset

````

````{py:method} _terminate_processes(request, processes)
:canonical: archivebox.machine.admin.ProcessAdmin._terminate_processes

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin._terminate_processes
```

````

````{py:method} kill_processes(request, queryset)
:canonical: archivebox.machine.admin.ProcessAdmin.kill_processes

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.kill_processes
```

````

````{py:method} kill_process(request, obj)
:canonical: archivebox.machine.admin.ProcessAdmin.kill_process

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.kill_process
```

````

````{py:method} machine_info(process)
:canonical: archivebox.machine.admin.ProcessAdmin.machine_info

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.machine_info
```

````

````{py:method} binary_info(process)
:canonical: archivebox.machine.admin.ProcessAdmin.binary_info

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.binary_info
```

````

````{py:method} binary_link(process)
:canonical: archivebox.machine.admin.ProcessAdmin.binary_link

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.binary_link
```

````

````{py:method} iface_link(process)
:canonical: archivebox.machine.admin.ProcessAdmin.iface_link

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.iface_link
```

````

````{py:method} archiveresult_link(process)
:canonical: archivebox.machine.admin.ProcessAdmin.archiveresult_link

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.archiveresult_link
```

````

````{py:method} snapshot_link(process)
:canonical: archivebox.machine.admin.ProcessAdmin.snapshot_link

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.snapshot_link
```

````

````{py:method} crawl_link(process)
:canonical: archivebox.machine.admin.ProcessAdmin.crawl_link

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.crawl_link
```

````

````{py:method} cmd_str(process)
:canonical: archivebox.machine.admin.ProcessAdmin.cmd_str

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.cmd_str
```

````

````{py:method} status_badge(process)
:canonical: archivebox.machine.admin.ProcessAdmin.status_badge

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.status_badge
```

````

````{py:method} duration_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.duration_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.duration_display
```

````

````{py:method} output_summary(process)
:canonical: archivebox.machine.admin.ProcessAdmin.output_summary

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.output_summary
```

````

````{py:method} cmd_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.cmd_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.cmd_display
```

````

````{py:method} env_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.env_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.env_display
```

````

````{py:method} stdout_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.stdout_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.stdout_display
```

````

````{py:method} stderr_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.stderr_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.stderr_display
```

````

````{py:method} archiveresult_output_display(process)
:canonical: archivebox.machine.admin.ProcessAdmin.archiveresult_output_display

```{autodoc2-docstring} archivebox.machine.admin.ProcessAdmin.archiveresult_output_display
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.machine.admin.register_admin

```{autodoc2-docstring} archivebox.machine.admin.register_admin
```
````
