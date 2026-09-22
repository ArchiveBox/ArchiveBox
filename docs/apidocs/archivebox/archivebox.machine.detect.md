# {py:mod}`archivebox.machine.detect`

```{py:module} archivebox.machine.detect
```

```{autodoc2-docstring} archivebox.machine.detect
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_vm_info <archivebox.machine.detect.get_vm_info>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_vm_info
    :summary:
    ```
* - {py:obj}`get_public_ip <archivebox.machine.detect.get_public_ip>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_public_ip
    :summary:
    ```
* - {py:obj}`get_local_ip <archivebox.machine.detect.get_local_ip>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_local_ip
    :summary:
    ```
* - {py:obj}`unknown_if_blank <archivebox.machine.detect.unknown_if_blank>`
  - ```{autodoc2-docstring} archivebox.machine.detect.unknown_if_blank
    :summary:
    ```
* - {py:obj}`get_isp_info <archivebox.machine.detect.get_isp_info>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_isp_info
    :summary:
    ```
* - {py:obj}`get_host_network <archivebox.machine.detect.get_host_network>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_host_network
    :summary:
    ```
* - {py:obj}`get_os_info <archivebox.machine.detect.get_os_info>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_os_info
    :summary:
    ```
* - {py:obj}`get_host_stats <archivebox.machine.detect.get_host_stats>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_host_stats
    :summary:
    ```
* - {py:obj}`get_host_guid <archivebox.machine.detect.get_host_guid>`
  - ```{autodoc2-docstring} archivebox.machine.detect.get_host_guid
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PACKAGE_DIR <archivebox.machine.detect.PACKAGE_DIR>`
  - ```{autodoc2-docstring} archivebox.machine.detect.PACKAGE_DIR
    :summary:
    ```
* - {py:obj}`DATA_DIR <archivebox.machine.detect.DATA_DIR>`
  - ```{autodoc2-docstring} archivebox.machine.detect.DATA_DIR
    :summary:
    ```
* - {py:obj}`ip_addrs <archivebox.machine.detect.ip_addrs>`
  - ```{autodoc2-docstring} archivebox.machine.detect.ip_addrs
    :summary:
    ```
* - {py:obj}`mac_addrs <archivebox.machine.detect.mac_addrs>`
  - ```{autodoc2-docstring} archivebox.machine.detect.mac_addrs
    :summary:
    ```
````

### API

````{py:data} PACKAGE_DIR
:canonical: archivebox.machine.detect.PACKAGE_DIR
:value: >
   None

```{autodoc2-docstring} archivebox.machine.detect.PACKAGE_DIR
```

````

````{py:data} DATA_DIR
:canonical: archivebox.machine.detect.DATA_DIR
:value: >
   'resolve(...)'

```{autodoc2-docstring} archivebox.machine.detect.DATA_DIR
```

````

````{py:function} get_vm_info()
:canonical: archivebox.machine.detect.get_vm_info

```{autodoc2-docstring} archivebox.machine.detect.get_vm_info
```
````

````{py:function} get_public_ip() -> str
:canonical: archivebox.machine.detect.get_public_ip

```{autodoc2-docstring} archivebox.machine.detect.get_public_ip
```
````

````{py:function} get_local_ip(remote_ip: str = '1.1.1.1', remote_port: int = 80) -> str
:canonical: archivebox.machine.detect.get_local_ip

```{autodoc2-docstring} archivebox.machine.detect.get_local_ip
```
````

````{py:data} ip_addrs
:canonical: archivebox.machine.detect.ip_addrs
:value: >
   None

```{autodoc2-docstring} archivebox.machine.detect.ip_addrs
```

````

````{py:data} mac_addrs
:canonical: archivebox.machine.detect.mac_addrs
:value: >
   None

```{autodoc2-docstring} archivebox.machine.detect.mac_addrs
```

````

````{py:function} unknown_if_blank(value)
:canonical: archivebox.machine.detect.unknown_if_blank

```{autodoc2-docstring} archivebox.machine.detect.unknown_if_blank
```
````

````{py:function} get_isp_info(ip=None)
:canonical: archivebox.machine.detect.get_isp_info

```{autodoc2-docstring} archivebox.machine.detect.get_isp_info
```
````

````{py:function} get_host_network() -> dict[str, typing.Any]
:canonical: archivebox.machine.detect.get_host_network

```{autodoc2-docstring} archivebox.machine.detect.get_host_network
```
````

````{py:function} get_os_info() -> dict[str, typing.Any]
:canonical: archivebox.machine.detect.get_os_info

```{autodoc2-docstring} archivebox.machine.detect.get_os_info
```
````

````{py:function} get_host_stats() -> dict[str, typing.Any]
:canonical: archivebox.machine.detect.get_host_stats

```{autodoc2-docstring} archivebox.machine.detect.get_host_stats
```
````

````{py:function} get_host_guid() -> str
:canonical: archivebox.machine.detect.get_host_guid

```{autodoc2-docstring} archivebox.machine.detect.get_host_guid
```
````
