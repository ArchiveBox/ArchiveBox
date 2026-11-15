# {py:mod}`archivebox.domains.export_service`

```{py:module} archivebox.domains.export_service
```

```{autodoc2-docstring} archivebox.domains.export_service
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`export_log_prefix <archivebox.domains.export_service.export_log_prefix>`
  - ```{autodoc2-docstring} archivebox.domains.export_service.export_log_prefix
    :summary:
    ```
* - {py:obj}`launch_export <archivebox.domains.export_service.launch_export>`
  - ```{autodoc2-docstring} archivebox.domains.export_service.launch_export
    :summary:
    ```
* - {py:obj}`export_jobs <archivebox.domains.export_service.export_jobs>`
  - ```{autodoc2-docstring} archivebox.domains.export_service.export_jobs
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FORMATS <archivebox.domains.export_service.FORMATS>`
  - ```{autodoc2-docstring} archivebox.domains.export_service.FORMATS
    :summary:
    ```
````

### API

````{py:data} FORMATS
:canonical: archivebox.domains.export_service.FORMATS
:value: >
   None

```{autodoc2-docstring} archivebox.domains.export_service.FORMATS
```

````

````{py:function} export_log_prefix(scope=None, *, query=None, user=None, public_only=False)
:canonical: archivebox.domains.export_service.export_log_prefix

```{autodoc2-docstring} archivebox.domains.export_service.export_log_prefix
```
````

````{py:function} launch_export(crawl=None, *, scope=None, query=None, user=None, public_only=False, directory, format, max_bytes=None)
:canonical: archivebox.domains.export_service.launch_export

```{autodoc2-docstring} archivebox.domains.export_service.launch_export
```
````

````{py:function} export_jobs(crawl=None, *, scope=None, query=None, user=None, public_only=False, process_id=None)
:canonical: archivebox.domains.export_service.export_jobs

```{autodoc2-docstring} archivebox.domains.export_service.export_jobs
```
````
