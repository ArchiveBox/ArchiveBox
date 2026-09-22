# {py:mod}`archivebox.api.v1_cli`

```{py:module} archivebox.api.v1_cli
```

```{autodoc2-docstring} archivebox.api.v1_cli
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CLICommandResponseSchema <archivebox.api.v1_cli.CLICommandResponseSchema>`
  -
* - {py:obj}`AddCommandSchema <archivebox.api.v1_cli.AddCommandSchema>`
  -
* - {py:obj}`SnapshotFilterCommandSchema <archivebox.api.v1_cli.SnapshotFilterCommandSchema>`
  -
* - {py:obj}`UpdateCommandSchema <archivebox.api.v1_cli.UpdateCommandSchema>`
  -
* - {py:obj}`ScheduleCommandSchema <archivebox.api.v1_cli.ScheduleCommandSchema>`
  -
* - {py:obj}`ListCommandSchema <archivebox.api.v1_cli.ListCommandSchema>`
  -
* - {py:obj}`RemoveCommandSchema <archivebox.api.v1_cli.RemoveCommandSchema>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`snapshot_filter_kwargs <archivebox.api.v1_cli.snapshot_filter_kwargs>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.snapshot_filter_kwargs
    :summary:
    ```
* - {py:obj}`cli_add <archivebox.api.v1_cli.cli_add>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.cli_add
    :summary:
    ```
* - {py:obj}`cli_update <archivebox.api.v1_cli.cli_update>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.cli_update
    :summary:
    ```
* - {py:obj}`cli_schedule <archivebox.api.v1_cli.cli_schedule>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.cli_schedule
    :summary:
    ```
* - {py:obj}`cli_search <archivebox.api.v1_cli.cli_search>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.cli_search
    :summary:
    ```
* - {py:obj}`cli_remove <archivebox.api.v1_cli.cli_remove>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.cli_remove
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_cli.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.router
    :summary:
    ```
* - {py:obj}`JSONType <archivebox.api.v1_cli.JSONType>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.JSONType
    :summary:
    ```
* - {py:obj}`FILTER_PATTERNS_EXAMPLES <archivebox.api.v1_cli.FILTER_PATTERNS_EXAMPLES>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.FILTER_PATTERNS_EXAMPLES
    :summary:
    ```
* - {py:obj}`FilterTypeChoices <archivebox.api.v1_cli.FilterTypeChoices>`
  - ```{autodoc2-docstring} archivebox.api.v1_cli.FilterTypeChoices
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_cli.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_cli.router
```

````

````{py:data} JSONType
:canonical: archivebox.api.v1_cli.JSONType
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.JSONType
```

````

````{py:data} FILTER_PATTERNS_EXAMPLES
:canonical: archivebox.api.v1_cli.FILTER_PATTERNS_EXAMPLES
:value: >
   [['https://example.com']]

```{autodoc2-docstring} archivebox.api.v1_cli.FILTER_PATTERNS_EXAMPLES
```

````

`````{py:class} CLICommandResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.success
```

````

````{py:attribute} errors
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.errors
:type: list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.errors
```

````

````{py:attribute} result
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.result
:type: archivebox.api.v1_cli.JSONType
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.result
```

````

````{py:attribute} result_format
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.result_format
:type: str
:value: >
   'str'

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.result_format
```

````

````{py:attribute} stdout
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.stdout
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.stdout
```

````

````{py:attribute} stderr
:canonical: archivebox.api.v1_cli.CLICommandResponseSchema.stderr
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.CLICommandResponseSchema.stderr
```

````

`````

````{py:data} FilterTypeChoices
:canonical: archivebox.api.v1_cli.FilterTypeChoices
:value: >
   'Enum(...)'

```{autodoc2-docstring} archivebox.api.v1_cli.FilterTypeChoices
```

````

`````{py:class} AddCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.AddCommandSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} urls
:canonical: archivebox.api.v1_cli.AddCommandSchema.urls
:type: list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.urls
```

````

````{py:attribute} snapshot_ids
:canonical: archivebox.api.v1_cli.AddCommandSchema.snapshot_ids
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.snapshot_ids
```

````

````{py:attribute} tag
:canonical: archivebox.api.v1_cli.AddCommandSchema.tag
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.tag
```

````

````{py:attribute} depth
:canonical: archivebox.api.v1_cli.AddCommandSchema.depth
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.depth
```

````

````{py:attribute} max_urls
:canonical: archivebox.api.v1_cli.AddCommandSchema.max_urls
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.max_urls
```

````

````{py:attribute} crawl_max_size
:canonical: archivebox.api.v1_cli.AddCommandSchema.crawl_max_size
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.crawl_max_size
```

````

````{py:attribute} crawl_timeout
:canonical: archivebox.api.v1_cli.AddCommandSchema.crawl_timeout
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.crawl_timeout
```

````

````{py:attribute} snapshot_max_size
:canonical: archivebox.api.v1_cli.AddCommandSchema.snapshot_max_size
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.snapshot_max_size
```

````

````{py:attribute} parser
:canonical: archivebox.api.v1_cli.AddCommandSchema.parser
:type: str
:value: >
   'auto'

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.parser
```

````

````{py:attribute} plugins
:canonical: archivebox.api.v1_cli.AddCommandSchema.plugins
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.plugins
```

````

````{py:attribute} persona
:canonical: archivebox.api.v1_cli.AddCommandSchema.persona
:type: str
:value: >
   'Default'

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.persona
```

````

````{py:attribute} only_new
:canonical: archivebox.api.v1_cli.AddCommandSchema.only_new
:type: bool | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.only_new
```

````

````{py:attribute} update
:canonical: archivebox.api.v1_cli.AddCommandSchema.update
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.update
```

````

````{py:attribute} overwrite
:canonical: archivebox.api.v1_cli.AddCommandSchema.overwrite
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.overwrite
```

````

````{py:attribute} index_only
:canonical: archivebox.api.v1_cli.AddCommandSchema.index_only
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.AddCommandSchema.index_only
```

````

`````

`````{py:class} SnapshotFilterCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} after
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.after
:type: float | None
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.after
```

````

````{py:attribute} before
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.before
:type: float | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.before
```

````

````{py:attribute} filter_type
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.filter_type
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.filter_type
```

````

````{py:attribute} filter_patterns
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.filter_patterns
:type: list[str] | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.filter_patterns
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.status
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.status
```

````

````{py:attribute} url__icontains
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.url__icontains
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.url__icontains
```

````

````{py:attribute} url__istartswith
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.url__istartswith
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.url__istartswith
```

````

````{py:attribute} tag
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.tag
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.tag
```

````

````{py:attribute} crawl_id
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.crawl_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.crawl_id
```

````

````{py:attribute} limit
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.limit
:type: int | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.limit
```

````

````{py:attribute} sort
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.sort
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.sort
```

````

````{py:attribute} search
:canonical: archivebox.api.v1_cli.SnapshotFilterCommandSchema.search
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.SnapshotFilterCommandSchema.search
```

````

`````

`````{py:class} UpdateCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.UpdateCommandSchema

Bases: {py:obj}`archivebox.api.v1_cli.SnapshotFilterCommandSchema`

````{py:attribute} resume
:canonical: archivebox.api.v1_cli.UpdateCommandSchema.resume
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.UpdateCommandSchema.resume
```

````

````{py:attribute} batch_size
:canonical: archivebox.api.v1_cli.UpdateCommandSchema.batch_size
:type: int
:value: >
   100

```{autodoc2-docstring} archivebox.api.v1_cli.UpdateCommandSchema.batch_size
```

````

````{py:attribute} continuous
:canonical: archivebox.api.v1_cli.UpdateCommandSchema.continuous
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.UpdateCommandSchema.continuous
```

````

````{py:attribute} index_only
:canonical: archivebox.api.v1_cli.UpdateCommandSchema.index_only
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.UpdateCommandSchema.index_only
```

````

````{py:attribute} migrate_only
:canonical: archivebox.api.v1_cli.UpdateCommandSchema.migrate_only
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.UpdateCommandSchema.migrate_only
```

````

`````

`````{py:class} ScheduleCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} import_path
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.import_path
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.import_path
```

````

````{py:attribute} add
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.add
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.add
```

````

````{py:attribute} show
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.show
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.show
```

````

````{py:attribute} foreground
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.foreground
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.foreground
```

````

````{py:attribute} run_all
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.run_all
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.run_all
```

````

````{py:attribute} quiet
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.quiet
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.quiet
```

````

````{py:attribute} every
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.every
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.every
```

````

````{py:attribute} tag
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.tag
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.tag
```

````

````{py:attribute} depth
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.depth
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.depth
```

````

````{py:attribute} only_new
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.only_new
:type: bool | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.only_new
```

````

````{py:attribute} update
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.update
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.update
```

````

````{py:attribute} overwrite
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.overwrite
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.overwrite
```

````

````{py:attribute} clear
:canonical: archivebox.api.v1_cli.ScheduleCommandSchema.clear
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ScheduleCommandSchema.clear
```

````

`````

`````{py:class} ListCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.ListCommandSchema

Bases: {py:obj}`archivebox.api.v1_cli.SnapshotFilterCommandSchema`

````{py:attribute} as_json
:canonical: archivebox.api.v1_cli.ListCommandSchema.as_json
:type: bool
:value: >
   True

```{autodoc2-docstring} archivebox.api.v1_cli.ListCommandSchema.as_json
```

````

````{py:attribute} as_html
:canonical: archivebox.api.v1_cli.ListCommandSchema.as_html
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ListCommandSchema.as_html
```

````

````{py:attribute} as_csv
:canonical: archivebox.api.v1_cli.ListCommandSchema.as_csv
:type: str | None
:value: >
   'timestamp,url'

```{autodoc2-docstring} archivebox.api.v1_cli.ListCommandSchema.as_csv
```

````

````{py:attribute} with_headers
:canonical: archivebox.api.v1_cli.ListCommandSchema.with_headers
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.api.v1_cli.ListCommandSchema.with_headers
```

````

`````

`````{py:class} RemoveCommandSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_cli.RemoveCommandSchema

Bases: {py:obj}`archivebox.api.v1_cli.SnapshotFilterCommandSchema`

````{py:attribute} filter_type
:canonical: archivebox.api.v1_cli.RemoveCommandSchema.filter_type
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_cli.RemoveCommandSchema.filter_type
```

````

````{py:attribute} timeout
:canonical: archivebox.api.v1_cli.RemoveCommandSchema.timeout
:type: float
:value: >
   60.0

```{autodoc2-docstring} archivebox.api.v1_cli.RemoveCommandSchema.timeout
```

````

`````

````{py:function} snapshot_filter_kwargs(args: archivebox.api.v1_cli.SnapshotFilterCommandSchema, *, default_filter_type: str) -> dict[str, typing.Any]
:canonical: archivebox.api.v1_cli.snapshot_filter_kwargs

```{autodoc2-docstring} archivebox.api.v1_cli.snapshot_filter_kwargs
```
````

````{py:function} cli_add(request: django.http.HttpRequest, args: archivebox.api.v1_cli.AddCommandSchema)
:canonical: archivebox.api.v1_cli.cli_add

```{autodoc2-docstring} archivebox.api.v1_cli.cli_add
```
````

````{py:function} cli_update(request: django.http.HttpRequest, args: archivebox.api.v1_cli.UpdateCommandSchema)
:canonical: archivebox.api.v1_cli.cli_update

```{autodoc2-docstring} archivebox.api.v1_cli.cli_update
```
````

````{py:function} cli_schedule(request: django.http.HttpRequest, args: archivebox.api.v1_cli.ScheduleCommandSchema)
:canonical: archivebox.api.v1_cli.cli_schedule

```{autodoc2-docstring} archivebox.api.v1_cli.cli_schedule
```
````

````{py:function} cli_search(request: django.http.HttpRequest, args: archivebox.api.v1_cli.ListCommandSchema)
:canonical: archivebox.api.v1_cli.cli_search

```{autodoc2-docstring} archivebox.api.v1_cli.cli_search
```
````

````{py:function} cli_remove(request: django.http.HttpRequest, args: archivebox.api.v1_cli.RemoveCommandSchema)
:canonical: archivebox.api.v1_cli.cli_remove

```{autodoc2-docstring} archivebox.api.v1_cli.cli_remove
```
````
