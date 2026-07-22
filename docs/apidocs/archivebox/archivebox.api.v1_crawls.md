# {py:mod}`archivebox.api.v1_crawls`

```{py:module} archivebox.api.v1_crawls
```

```{autodoc2-docstring} archivebox.api.v1_crawls
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CrawlSchema <archivebox.api.v1_crawls.CrawlSchema>`
  -
* - {py:obj}`CrawlUpdateSchema <archivebox.api.v1_crawls.CrawlUpdateSchema>`
  -
* - {py:obj}`CrawlCreateSchema <archivebox.api.v1_crawls.CrawlCreateSchema>`
  -
* - {py:obj}`CrawlDeleteResponseSchema <archivebox.api.v1_crawls.CrawlDeleteResponseSchema>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`normalize_tag_list <archivebox.api.v1_crawls.normalize_tag_list>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.normalize_tag_list
    :summary:
    ```
* - {py:obj}`get_crawls <archivebox.api.v1_crawls.get_crawls>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawls
    :summary:
    ```
* - {py:obj}`create_crawl <archivebox.api.v1_crawls.create_crawl>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.create_crawl
    :summary:
    ```
* - {py:obj}`get_crawl_by_ref <archivebox.api.v1_crawls.get_crawl_by_ref>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawl_by_ref
    :summary:
    ```
* - {py:obj}`get_crawl <archivebox.api.v1_crawls.get_crawl>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawl
    :summary:
    ```
* - {py:obj}`crawl_file <archivebox.api.v1_crawls.crawl_file>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file
    :summary:
    ```
* - {py:obj}`crawl_file_root <archivebox.api.v1_crawls.crawl_file_root>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_root
    :summary:
    ```
* - {py:obj}`crawl_file_nested_1 <archivebox.api.v1_crawls.crawl_file_nested_1>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_nested_1
    :summary:
    ```
* - {py:obj}`crawl_file_nested_2 <archivebox.api.v1_crawls.crawl_file_nested_2>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_nested_2
    :summary:
    ```
* - {py:obj}`patch_crawl <archivebox.api.v1_crawls.patch_crawl>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.patch_crawl
    :summary:
    ```
* - {py:obj}`delete_crawl <archivebox.api.v1_crawls.delete_crawl>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.delete_crawl
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_crawls.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_crawls.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_crawls.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_crawls.router
```

````

`````{py:class} CrawlSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_crawls.CrawlSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_crawls.CrawlSchema.TYPE
:type: str
:value: >
   'crawls.models.Crawl'

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_crawls.CrawlSchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.id
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_crawls.CrawlSchema.modified_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.modified_at
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_crawls.CrawlSchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.created_at
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_crawls.CrawlSchema.created_by_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_crawls.CrawlSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.created_by_username
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_crawls.CrawlSchema.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.api.v1_crawls.CrawlSchema.retry_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.retry_at
```

````

````{py:attribute} is_paused
:canonical: archivebox.api.v1_crawls.CrawlSchema.is_paused
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.is_paused
```

````

````{py:attribute} urls
:canonical: archivebox.api.v1_crawls.CrawlSchema.urls
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.urls
```

````

````{py:attribute} max_depth
:canonical: archivebox.api.v1_crawls.CrawlSchema.max_depth
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.max_depth
```

````

````{py:attribute} tags_str
:canonical: archivebox.api.v1_crawls.CrawlSchema.tags_str
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.tags_str
```

````

````{py:attribute} config
:canonical: archivebox.api.v1_crawls.CrawlSchema.config
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.config
```

````

````{py:method} resolve_created_by_id(obj)
:canonical: archivebox.api.v1_crawls.CrawlSchema.resolve_created_by_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.resolve_created_by_id
```

````

````{py:method} resolve_created_by_username(obj)
:canonical: archivebox.api.v1_crawls.CrawlSchema.resolve_created_by_username
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.resolve_created_by_username
```

````

````{py:method} resolve_config(obj)
:canonical: archivebox.api.v1_crawls.CrawlSchema.resolve_config
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.resolve_config
```

````

````{py:method} resolve_snapshots(obj, context)
:canonical: archivebox.api.v1_crawls.CrawlSchema.resolve_snapshots
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlSchema.resolve_snapshots
```

````

`````

`````{py:class} CrawlUpdateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} action
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema.action
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlUpdateSchema.action
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema.status
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlUpdateSchema.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema.retry_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlUpdateSchema.retry_at
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema.tags
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlUpdateSchema.tags
```

````

````{py:attribute} tags_str
:canonical: archivebox.api.v1_crawls.CrawlUpdateSchema.tags_str
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlUpdateSchema.tags_str
```

````

`````

`````{py:class} CrawlCreateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} urls
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.urls
:type: list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.urls
```

````

````{py:attribute} max_depth
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.max_depth
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.max_depth
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.tags
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.tags
```

````

````{py:attribute} tags_str
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.tags_str
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.tags_str
```

````

````{py:attribute} label
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.label
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.label
```

````

````{py:attribute} notes
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.notes
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.notes
```

````

````{py:attribute} config
:canonical: archivebox.api.v1_crawls.CrawlCreateSchema.config
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlCreateSchema.config
```

````

`````

`````{py:class} CrawlDeleteResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_crawls.CrawlDeleteResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_crawls.CrawlDeleteResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlDeleteResponseSchema.success
```

````

````{py:attribute} crawl_id
:canonical: archivebox.api.v1_crawls.CrawlDeleteResponseSchema.crawl_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlDeleteResponseSchema.crawl_id
```

````

````{py:attribute} deleted_count
:canonical: archivebox.api.v1_crawls.CrawlDeleteResponseSchema.deleted_count
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlDeleteResponseSchema.deleted_count
```

````

````{py:attribute} deleted_snapshots
:canonical: archivebox.api.v1_crawls.CrawlDeleteResponseSchema.deleted_snapshots
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_crawls.CrawlDeleteResponseSchema.deleted_snapshots
```

````

`````

````{py:function} normalize_tag_list(tags: list[str] | None = None, tags_str: str = '') -> list[str]
:canonical: archivebox.api.v1_crawls.normalize_tag_list

```{autodoc2-docstring} archivebox.api.v1_crawls.normalize_tag_list
```
````

````{py:function} get_crawls(request: django.http.HttpRequest)
:canonical: archivebox.api.v1_crawls.get_crawls

```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawls
```
````

````{py:function} create_crawl(request: django.http.HttpRequest, data: archivebox.api.v1_crawls.CrawlCreateSchema)
:canonical: archivebox.api.v1_crawls.create_crawl

```{autodoc2-docstring} archivebox.api.v1_crawls.create_crawl
```
````

````{py:function} get_crawl_by_ref(crawl_id: str)
:canonical: archivebox.api.v1_crawls.get_crawl_by_ref

```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawl_by_ref
```
````

````{py:function} get_crawl(request: django.http.HttpRequest, crawl_id: str, as_rss: bool = False, with_snapshots: bool = False, with_archiveresults: bool = False)
:canonical: archivebox.api.v1_crawls.get_crawl

```{autodoc2-docstring} archivebox.api.v1_crawls.get_crawl
```
````

````{py:function} crawl_file(request: django.http.HttpRequest, crawl_id: str, path: str)
:canonical: archivebox.api.v1_crawls.crawl_file

```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file
```
````

````{py:function} crawl_file_root(request: django.http.HttpRequest, crawl_id: str, filename: str)
:canonical: archivebox.api.v1_crawls.crawl_file_root

```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_root
```
````

````{py:function} crawl_file_nested_1(request: django.http.HttpRequest, crawl_id: str, folder: str, filename: str)
:canonical: archivebox.api.v1_crawls.crawl_file_nested_1

```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_nested_1
```
````

````{py:function} crawl_file_nested_2(request: django.http.HttpRequest, crawl_id: str, folder: str, subfolder: str, filename: str)
:canonical: archivebox.api.v1_crawls.crawl_file_nested_2

```{autodoc2-docstring} archivebox.api.v1_crawls.crawl_file_nested_2
```
````

````{py:function} patch_crawl(request: django.http.HttpRequest, crawl_id: str, data: archivebox.api.v1_crawls.CrawlUpdateSchema)
:canonical: archivebox.api.v1_crawls.patch_crawl

```{autodoc2-docstring} archivebox.api.v1_crawls.patch_crawl
```
````

````{py:function} delete_crawl(request: django.http.HttpRequest, crawl_id: str)
:canonical: archivebox.api.v1_crawls.delete_crawl

```{autodoc2-docstring} archivebox.api.v1_crawls.delete_crawl
```
````
