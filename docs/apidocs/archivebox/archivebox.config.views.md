# {py:mod}`archivebox.config.views`

```{py:module} archivebox.config.views
```

```{autodoc2-docstring} archivebox.config.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`is_superuser <archivebox.config.views.is_superuser>`
  - ```{autodoc2-docstring} archivebox.config.views.is_superuser
    :summary:
    ```
* - {py:obj}`format_parsed_datetime <archivebox.config.views.format_parsed_datetime>`
  - ```{autodoc2-docstring} archivebox.config.views.format_parsed_datetime
    :summary:
    ```
* - {py:obj}`get_environment_binary_url <archivebox.config.views.get_environment_binary_url>`
  - ```{autodoc2-docstring} archivebox.config.views.get_environment_binary_url
    :summary:
    ```
* - {py:obj}`get_installed_binary_change_url <archivebox.config.views.get_installed_binary_change_url>`
  - ```{autodoc2-docstring} archivebox.config.views.get_installed_binary_change_url
    :summary:
    ```
* - {py:obj}`render_binary_detail_description <archivebox.config.views.render_binary_detail_description>`
  - ```{autodoc2-docstring} archivebox.config.views.render_binary_detail_description
    :summary:
    ```
* - {py:obj}`obj_to_yaml <archivebox.config.views.obj_to_yaml>`
  - ```{autodoc2-docstring} archivebox.config.views.obj_to_yaml
    :summary:
    ```
* - {py:obj}`_binary_sort_key <archivebox.config.views._binary_sort_key>`
  - ```{autodoc2-docstring} archivebox.config.views._binary_sort_key
    :summary:
    ```
* - {py:obj}`get_db_binaries_by_name <archivebox.config.views.get_db_binaries_by_name>`
  - ```{autodoc2-docstring} archivebox.config.views.get_db_binaries_by_name
    :summary:
    ```
* - {py:obj}`binaries_list_view <archivebox.config.views.binaries_list_view>`
  - ```{autodoc2-docstring} archivebox.config.views.binaries_list_view
    :summary:
    ```
* - {py:obj}`binary_detail_view <archivebox.config.views.binary_detail_view>`
  - ```{autodoc2-docstring} archivebox.config.views.binary_detail_view
    :summary:
    ```
* - {py:obj}`worker_list_view <archivebox.config.views.worker_list_view>`
  - ```{autodoc2-docstring} archivebox.config.views.worker_list_view
    :summary:
    ```
* - {py:obj}`worker_detail_view <archivebox.config.views.worker_detail_view>`
  - ```{autodoc2-docstring} archivebox.config.views.worker_detail_view
    :summary:
    ```
* - {py:obj}`log_list_view <archivebox.config.views.log_list_view>`
  - ```{autodoc2-docstring} archivebox.config.views.log_list_view
    :summary:
    ```
* - {py:obj}`log_detail_view <archivebox.config.views.log_detail_view>`
  - ```{autodoc2-docstring} archivebox.config.views.log_detail_view
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ENVIRONMENT_BINARIES_BASE_URL <archivebox.config.views.ENVIRONMENT_BINARIES_BASE_URL>`
  - ```{autodoc2-docstring} archivebox.config.views.ENVIRONMENT_BINARIES_BASE_URL
    :summary:
    ```
* - {py:obj}`INSTALLED_BINARIES_BASE_URL <archivebox.config.views.INSTALLED_BINARIES_BASE_URL>`
  - ```{autodoc2-docstring} archivebox.config.views.INSTALLED_BINARIES_BASE_URL
    :summary:
    ```
````

### API

````{py:data} ENVIRONMENT_BINARIES_BASE_URL
:canonical: archivebox.config.views.ENVIRONMENT_BINARIES_BASE_URL
:value: >
   '/admin/environment/binaries/'

```{autodoc2-docstring} archivebox.config.views.ENVIRONMENT_BINARIES_BASE_URL
```

````

````{py:data} INSTALLED_BINARIES_BASE_URL
:canonical: archivebox.config.views.INSTALLED_BINARIES_BASE_URL
:value: >
   '/admin/machine/binary/'

```{autodoc2-docstring} archivebox.config.views.INSTALLED_BINARIES_BASE_URL
```

````

````{py:function} is_superuser(request: django.http.HttpRequest) -> bool
:canonical: archivebox.config.views.is_superuser

```{autodoc2-docstring} archivebox.config.views.is_superuser
```
````

````{py:function} format_parsed_datetime(value: object) -> str
:canonical: archivebox.config.views.format_parsed_datetime

```{autodoc2-docstring} archivebox.config.views.format_parsed_datetime
```
````

````{py:function} get_environment_binary_url(name: str) -> str
:canonical: archivebox.config.views.get_environment_binary_url

```{autodoc2-docstring} archivebox.config.views.get_environment_binary_url
```
````

````{py:function} get_installed_binary_change_url(name: str, binary: archivebox.machine.models.Binary | None) -> str | None
:canonical: archivebox.config.views.get_installed_binary_change_url

```{autodoc2-docstring} archivebox.config.views.get_installed_binary_change_url
```
````

````{py:function} render_binary_detail_description(name: str, merged: dict[str, typing.Any], db_binary: typing.Any) -> str
:canonical: archivebox.config.views.render_binary_detail_description

```{autodoc2-docstring} archivebox.config.views.render_binary_detail_description
```
````

````{py:function} obj_to_yaml(obj: typing.Any, indent: int = 0) -> str
:canonical: archivebox.config.views.obj_to_yaml

```{autodoc2-docstring} archivebox.config.views.obj_to_yaml
```
````

````{py:function} _binary_sort_key(binary: archivebox.machine.models.Binary) -> tuple[int, int, int, typing.Any]
:canonical: archivebox.config.views._binary_sort_key

```{autodoc2-docstring} archivebox.config.views._binary_sort_key
```
````

````{py:function} get_db_binaries_by_name() -> dict[str, archivebox.machine.models.Binary]
:canonical: archivebox.config.views.get_db_binaries_by_name

```{autodoc2-docstring} archivebox.config.views.get_db_binaries_by_name
```
````

````{py:function} binaries_list_view(request: django.http.HttpRequest, **kwargs) -> admin_data_views.typing.TableContext
:canonical: archivebox.config.views.binaries_list_view

```{autodoc2-docstring} archivebox.config.views.binaries_list_view
```
````

````{py:function} binary_detail_view(request: django.http.HttpRequest, key: str, **kwargs) -> admin_data_views.typing.ItemContext
:canonical: archivebox.config.views.binary_detail_view

```{autodoc2-docstring} archivebox.config.views.binary_detail_view
```
````

````{py:function} worker_list_view(request: django.http.HttpRequest, **kwargs) -> admin_data_views.typing.TableContext
:canonical: archivebox.config.views.worker_list_view

```{autodoc2-docstring} archivebox.config.views.worker_list_view
```
````

````{py:function} worker_detail_view(request: django.http.HttpRequest, key: str, **kwargs) -> admin_data_views.typing.ItemContext
:canonical: archivebox.config.views.worker_detail_view

```{autodoc2-docstring} archivebox.config.views.worker_detail_view
```
````

````{py:function} log_list_view(request: django.http.HttpRequest, **kwargs) -> admin_data_views.typing.TableContext
:canonical: archivebox.config.views.log_list_view

```{autodoc2-docstring} archivebox.config.views.log_list_view
```
````

````{py:function} log_detail_view(request: django.http.HttpRequest, key: str, **kwargs) -> admin_data_views.typing.ItemContext
:canonical: archivebox.config.views.log_detail_view

```{autodoc2-docstring} archivebox.config.views.log_detail_view
```
````
