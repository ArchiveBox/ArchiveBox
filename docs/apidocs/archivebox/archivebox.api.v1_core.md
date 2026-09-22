# {py:mod}`archivebox.api.v1_core`

```{py:module} archivebox.api.v1_core
```

```{autodoc2-docstring} archivebox.api.v1_core
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CustomPagination <archivebox.api.v1_core.CustomPagination>`
  -
* - {py:obj}`MinimalArchiveResultSchema <archivebox.api.v1_core.MinimalArchiveResultSchema>`
  -
* - {py:obj}`ArchiveResultSchema <archivebox.api.v1_core.ArchiveResultSchema>`
  -
* - {py:obj}`ArchiveResultFilterSchema <archivebox.api.v1_core.ArchiveResultFilterSchema>`
  -
* - {py:obj}`SnapshotSchema <archivebox.api.v1_core.SnapshotSchema>`
  -
* - {py:obj}`SnapshotUpdateSchema <archivebox.api.v1_core.SnapshotUpdateSchema>`
  -
* - {py:obj}`SnapshotCreateSchema <archivebox.api.v1_core.SnapshotCreateSchema>`
  -
* - {py:obj}`SnapshotDeleteResponseSchema <archivebox.api.v1_core.SnapshotDeleteResponseSchema>`
  -
* - {py:obj}`SnapshotFilterSchema <archivebox.api.v1_core.SnapshotFilterSchema>`
  -
* - {py:obj}`TagSchema <archivebox.api.v1_core.TagSchema>`
  -
* - {py:obj}`TagAutocompleteSchema <archivebox.api.v1_core.TagAutocompleteSchema>`
  -
* - {py:obj}`TagCreateSchema <archivebox.api.v1_core.TagCreateSchema>`
  -
* - {py:obj}`TagCreateResponseSchema <archivebox.api.v1_core.TagCreateResponseSchema>`
  -
* - {py:obj}`TagSearchSnapshotSchema <archivebox.api.v1_core.TagSearchSnapshotSchema>`
  -
* - {py:obj}`TagSearchCardSchema <archivebox.api.v1_core.TagSearchCardSchema>`
  -
* - {py:obj}`TagSearchResponseSchema <archivebox.api.v1_core.TagSearchResponseSchema>`
  -
* - {py:obj}`TagUpdateSchema <archivebox.api.v1_core.TagUpdateSchema>`
  -
* - {py:obj}`TagUpdateResponseSchema <archivebox.api.v1_core.TagUpdateResponseSchema>`
  -
* - {py:obj}`TagDeleteResponseSchema <archivebox.api.v1_core.TagDeleteResponseSchema>`
  -
* - {py:obj}`TagSnapshotRequestSchema <archivebox.api.v1_core.TagSnapshotRequestSchema>`
  -
* - {py:obj}`TagSnapshotResponseSchema <archivebox.api.v1_core.TagSnapshotResponseSchema>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_archiveresults <archivebox.api.v1_core.get_archiveresults>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_archiveresults
    :summary:
    ```
* - {py:obj}`_uuid_ref_query <archivebox.api.v1_core._uuid_ref_query>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._uuid_ref_query
    :summary:
    ```
* - {py:obj}`get_archiveresult <archivebox.api.v1_core.get_archiveresult>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_archiveresult
    :summary:
    ```
* - {py:obj}`_normalize_uploaded_archiveresult_plugin <archivebox.api.v1_core._normalize_uploaded_archiveresult_plugin>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._normalize_uploaded_archiveresult_plugin
    :summary:
    ```
* - {py:obj}`_normalize_uploaded_archiveresult_output_path <archivebox.api.v1_core._normalize_uploaded_archiveresult_output_path>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._normalize_uploaded_archiveresult_output_path
    :summary:
    ```
* - {py:obj}`_parse_archiveresult_output_json <archivebox.api.v1_core._parse_archiveresult_output_json>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._parse_archiveresult_output_json
    :summary:
    ```
* - {py:obj}`_get_archiveresult_upload_data <archivebox.api.v1_core._get_archiveresult_upload_data>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_data
    :summary:
    ```
* - {py:obj}`_get_archiveresult_upload_files <archivebox.api.v1_core._get_archiveresult_upload_files>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_files
    :summary:
    ```
* - {py:obj}`_get_archiveresult_upload_form_values <archivebox.api.v1_core._get_archiveresult_upload_form_values>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_form_values
    :summary:
    ```
* - {py:obj}`_get_archiveresult_upload_form_value <archivebox.api.v1_core._get_archiveresult_upload_form_value>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_form_value
    :summary:
    ```
* - {py:obj}`_parse_archiveresult_upload_int <archivebox.api.v1_core._parse_archiveresult_upload_int>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._parse_archiveresult_upload_int
    :summary:
    ```
* - {py:obj}`_summarize_archiveresult_output_files <archivebox.api.v1_core._summarize_archiveresult_output_files>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._summarize_archiveresult_output_files
    :summary:
    ```
* - {py:obj}`_get_snapshot_by_ref <archivebox.api.v1_core._get_snapshot_by_ref>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_snapshot_by_ref
    :summary:
    ```
* - {py:obj}`_queue_archiveresult_snapshot_maintenance <archivebox.api.v1_core._queue_archiveresult_snapshot_maintenance>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._queue_archiveresult_snapshot_maintenance
    :summary:
    ```
* - {py:obj}`_merge_archiveresult_output_file_maps <archivebox.api.v1_core._merge_archiveresult_output_file_maps>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._merge_archiveresult_output_file_maps
    :summary:
    ```
* - {py:obj}`_write_archiveresult_files <archivebox.api.v1_core._write_archiveresult_files>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._write_archiveresult_files
    :summary:
    ```
* - {py:obj}`create_archiveresult <archivebox.api.v1_core.create_archiveresult>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.create_archiveresult
    :summary:
    ```
* - {py:obj}`patch_archiveresult <archivebox.api.v1_core.patch_archiveresult>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.patch_archiveresult
    :summary:
    ```
* - {py:obj}`normalize_tag_list <archivebox.api.v1_core.normalize_tag_list>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.normalize_tag_list
    :summary:
    ```
* - {py:obj}`_parse_rss_before <archivebox.api.v1_core._parse_rss_before>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._parse_rss_before
    :summary:
    ```
* - {py:obj}`_filter_snapshots_for_rss <archivebox.api.v1_core._filter_snapshots_for_rss>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._filter_snapshots_for_rss
    :summary:
    ```
* - {py:obj}`_snapshots_rss_response <archivebox.api.v1_core._snapshots_rss_response>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._snapshots_rss_response
    :summary:
    ```
* - {py:obj}`get_snapshots <archivebox.api.v1_core.get_snapshots>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_snapshots
    :summary:
    ```
* - {py:obj}`get_snapshots_rss <archivebox.api.v1_core.get_snapshots_rss>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_snapshots_rss
    :summary:
    ```
* - {py:obj}`get_snapshot <archivebox.api.v1_core.get_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_snapshot
    :summary:
    ```
* - {py:obj}`create_snapshot <archivebox.api.v1_core.create_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.create_snapshot
    :summary:
    ```
* - {py:obj}`patch_snapshot <archivebox.api.v1_core.patch_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.patch_snapshot
    :summary:
    ```
* - {py:obj}`delete_snapshot <archivebox.api.v1_core.delete_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.delete_snapshot
    :summary:
    ```
* - {py:obj}`get_tags <archivebox.api.v1_core.get_tags>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_tags
    :summary:
    ```
* - {py:obj}`get_tag <archivebox.api.v1_core.get_tag>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_tag
    :summary:
    ```
* - {py:obj}`get_any <archivebox.api.v1_core.get_any>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.get_any
    :summary:
    ```
* - {py:obj}`_get_snapshot_for_tag_edit <archivebox.api.v1_core._get_snapshot_for_tag_edit>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._get_snapshot_for_tag_edit
    :summary:
    ```
* - {py:obj}`search_tags <archivebox.api.v1_core.search_tags>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.search_tags
    :summary:
    ```
* - {py:obj}`_public_tag_listing_enabled <archivebox.api.v1_core._public_tag_listing_enabled>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._public_tag_listing_enabled
    :summary:
    ```
* - {py:obj}`_request_has_tag_autocomplete_access <archivebox.api.v1_core._request_has_tag_autocomplete_access>`
  - ```{autodoc2-docstring} archivebox.api.v1_core._request_has_tag_autocomplete_access
    :summary:
    ```
* - {py:obj}`tags_autocomplete <archivebox.api.v1_core.tags_autocomplete>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tags_autocomplete
    :summary:
    ```
* - {py:obj}`tags_create <archivebox.api.v1_core.tags_create>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tags_create
    :summary:
    ```
* - {py:obj}`rename_tag <archivebox.api.v1_core.rename_tag>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.rename_tag
    :summary:
    ```
* - {py:obj}`delete_tag <archivebox.api.v1_core.delete_tag>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.delete_tag
    :summary:
    ```
* - {py:obj}`tag_urls_export <archivebox.api.v1_core.tag_urls_export>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tag_urls_export
    :summary:
    ```
* - {py:obj}`tag_snapshots_export <archivebox.api.v1_core.tag_snapshots_export>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tag_snapshots_export
    :summary:
    ```
* - {py:obj}`tags_add_to_snapshot <archivebox.api.v1_core.tags_add_to_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tags_add_to_snapshot
    :summary:
    ```
* - {py:obj}`tags_remove_from_snapshot <archivebox.api.v1_core.tags_remove_from_snapshot>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.tags_remove_from_snapshot
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_core.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.router
    :summary:
    ```
* - {py:obj}`ARCHIVERESULT_UPLOAD_HOOK_NAME <archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_HOOK_NAME>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_HOOK_NAME
    :summary:
    ```
* - {py:obj}`ARCHIVERESULT_UPLOAD_PLUGIN_RE <archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_PLUGIN_RE>`
  - ```{autodoc2-docstring} archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_PLUGIN_RE
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_core.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_core.router
```

````

````{py:data} ARCHIVERESULT_UPLOAD_HOOK_NAME
:canonical: archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_HOOK_NAME
:value: >
   'on_Snapshot__archivebox_browser_extension_upload'

```{autodoc2-docstring} archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_HOOK_NAME
```

````

````{py:data} ARCHIVERESULT_UPLOAD_PLUGIN_RE
:canonical: archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_PLUGIN_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.api.v1_core.ARCHIVERESULT_UPLOAD_PLUGIN_RE
```

````

``````{py:class} CustomPagination(*, pass_parameter: typing.Optional[str] = None, **kwargs: typing.Any)
:canonical: archivebox.api.v1_core.CustomPagination

Bases: {py:obj}`ninja.pagination.PaginationBase`

`````{py:class} Input(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.CustomPagination.Input

Bases: {py:obj}`ninja.pagination.PaginationBase.Input`

````{py:attribute} limit
:canonical: archivebox.api.v1_core.CustomPagination.Input.limit
:type: int
:value: >
   200

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Input.limit
```

````

````{py:attribute} offset
:canonical: archivebox.api.v1_core.CustomPagination.Input.offset
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Input.offset
```

````

````{py:attribute} page
:canonical: archivebox.api.v1_core.CustomPagination.Input.page
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Input.page
```

````

`````

`````{py:class} Output(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.CustomPagination.Output

Bases: {py:obj}`ninja.pagination.PaginationBase.Output`

````{py:attribute} count
:canonical: archivebox.api.v1_core.CustomPagination.Output.count
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.count
```

````

````{py:attribute} total_items
:canonical: archivebox.api.v1_core.CustomPagination.Output.total_items
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.total_items
```

````

````{py:attribute} total_pages
:canonical: archivebox.api.v1_core.CustomPagination.Output.total_pages
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.total_pages
```

````

````{py:attribute} page
:canonical: archivebox.api.v1_core.CustomPagination.Output.page
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.page
```

````

````{py:attribute} limit
:canonical: archivebox.api.v1_core.CustomPagination.Output.limit
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.limit
```

````

````{py:attribute} offset
:canonical: archivebox.api.v1_core.CustomPagination.Output.offset
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.offset
```

````

````{py:attribute} num_items
:canonical: archivebox.api.v1_core.CustomPagination.Output.num_items
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.num_items
```

````

````{py:attribute} items
:canonical: archivebox.api.v1_core.CustomPagination.Output.items
:type: list[typing.Any]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.Output.items
```

````

`````

````{py:method} paginate_queryset(queryset, pagination: Input, request: django.http.HttpRequest, **params)
:canonical: archivebox.api.v1_core.CustomPagination.paginate_queryset

```{autodoc2-docstring} archivebox.api.v1_core.CustomPagination.paginate_queryset
```

````

``````

`````{py:class} MinimalArchiveResultSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.TYPE
:type: str
:value: >
   'core.models.ArchiveResult'

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.id
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.created_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.modified_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.modified_at
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.created_by_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.created_by_username
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.retry_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.retry_at
```

````

````{py:attribute} plugin
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.plugin
```

````

````{py:attribute} hook_name
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.hook_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.hook_name
```

````

````{py:attribute} process_id
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.process_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.process_id
```

````

````{py:attribute} cmd_version
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.cmd_version
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.cmd_version
```

````

````{py:attribute} cmd
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.cmd
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.cmd
```

````

````{py:attribute} pwd
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.pwd
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.pwd
```

````

````{py:attribute} output_str
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.output_str
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.output_str
```

````

````{py:attribute} output_json
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.output_json
:type: dict[str, typing.Any] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.output_json
```

````

````{py:attribute} output_files
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.output_files
:type: dict[str, dict[str, typing.Any]] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.output_files
```

````

````{py:attribute} output_size
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.output_size
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.output_size
```

````

````{py:attribute} output_mimetypes
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.output_mimetypes
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.output_mimetypes
```

````

````{py:attribute} start_ts
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.start_ts
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.start_ts
```

````

````{py:attribute} end_ts
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.end_ts
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.end_ts
```

````

````{py:method} resolve_created_by_id(obj)
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_created_by_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_created_by_id
```

````

````{py:method} resolve_created_by_username(obj) -> str
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_created_by_username
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_created_by_username
```

````

````{py:method} resolve_output_files(obj)
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_output_files
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_output_files
```

````

````{py:method} resolve_output_mimetypes(obj) -> str
:canonical: archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_output_mimetypes
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.MinimalArchiveResultSchema.resolve_output_mimetypes
```

````

`````

`````{py:class} ArchiveResultSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.ArchiveResultSchema

Bases: {py:obj}`archivebox.api.v1_core.MinimalArchiveResultSchema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_core.ArchiveResultSchema.TYPE
:type: str
:value: >
   'core.models.ArchiveResult'

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.TYPE
```

````

````{py:attribute} snapshot_id
:canonical: archivebox.api.v1_core.ArchiveResultSchema.snapshot_id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.snapshot_id
```

````

````{py:attribute} snapshot_timestamp
:canonical: archivebox.api.v1_core.ArchiveResultSchema.snapshot_timestamp
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.snapshot_timestamp
```

````

````{py:attribute} snapshot_url
:canonical: archivebox.api.v1_core.ArchiveResultSchema.snapshot_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.snapshot_url
```

````

````{py:attribute} snapshot_tags
:canonical: archivebox.api.v1_core.ArchiveResultSchema.snapshot_tags
:type: list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.snapshot_tags
```

````

````{py:method} resolve_snapshot_timestamp(obj)
:canonical: archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_timestamp
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_timestamp
```

````

````{py:method} resolve_snapshot_url(obj)
:canonical: archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_url
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_url
```

````

````{py:method} resolve_snapshot_id(obj)
:canonical: archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_id
```

````

````{py:method} resolve_snapshot_tags(obj)
:canonical: archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_tags
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultSchema.resolve_snapshot_tags
```

````

`````

`````{py:class} ArchiveResultFilterSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema

Bases: {py:obj}`ninja.FilterSchema`

````{py:attribute} id
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.id
:type: typing.Annotated[str | None, FilterLookup(['id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.id
```

````

````{py:attribute} search
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.search
:type: typing.Annotated[str | None, FilterLookup(['snapshot__url__icontains', 'snapshot__title__icontains', 'snapshot__tags__name__icontains', 'plugin', 'output_str__icontains', 'id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.search
```

````

````{py:attribute} snapshot_id
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_id
:type: typing.Annotated[str | None, FilterLookup(['snapshot__id__startswith', 'snapshot__timestamp__startswith'])]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_id
```

````

````{py:attribute} snapshot_url
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_url
:type: typing.Annotated[str | None, FilterLookup('snapshot__url__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_url
```

````

````{py:attribute} snapshot_tag
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_tag
:type: typing.Annotated[str | None, FilterLookup('snapshot__tags__name__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.snapshot_tag
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.status
:type: typing.Annotated[str | None, FilterLookup('status')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.status
```

````

````{py:attribute} output_str
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.output_str
:type: typing.Annotated[str | None, FilterLookup('output_str__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.output_str
```

````

````{py:attribute} plugin
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.plugin
:type: typing.Annotated[str | None, FilterLookup('plugin__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.plugin
```

````

````{py:attribute} hook_name
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.hook_name
:type: typing.Annotated[str | None, FilterLookup('hook_name__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.hook_name
```

````

````{py:attribute} process_id
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.process_id
:type: typing.Annotated[str | None, FilterLookup('process__id__startswith')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.process_id
```

````

````{py:attribute} cmd
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.cmd
:type: typing.Annotated[str | None, FilterLookup('cmd__0__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.cmd
```

````

````{py:attribute} pwd
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.pwd
:type: typing.Annotated[str | None, FilterLookup('pwd__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.pwd
```

````

````{py:attribute} cmd_version
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.cmd_version
:type: typing.Annotated[str | None, FilterLookup('cmd_version')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.cmd_version
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.created_at
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.created_at
```

````

````{py:attribute} created_at__gte
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.created_at__gte
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at__gte')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.created_at__gte
```

````

````{py:attribute} created_at__lt
:canonical: archivebox.api.v1_core.ArchiveResultFilterSchema.created_at__lt
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at__lt')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.ArchiveResultFilterSchema.created_at__lt
```

````

`````

````{py:function} get_archiveresults(request: django.http.HttpRequest, filters: ninja.Query[archivebox.api.v1_core.ArchiveResultFilterSchema])
:canonical: archivebox.api.v1_core.get_archiveresults

```{autodoc2-docstring} archivebox.api.v1_core.get_archiveresults
```
````

````{py:function} _uuid_ref_query(field_name: str, ref: str) -> django.db.models.Q
:canonical: archivebox.api.v1_core._uuid_ref_query

```{autodoc2-docstring} archivebox.api.v1_core._uuid_ref_query
```
````

````{py:function} get_archiveresult(request: django.http.HttpRequest, archiveresult_id: str)
:canonical: archivebox.api.v1_core.get_archiveresult

```{autodoc2-docstring} archivebox.api.v1_core.get_archiveresult
```
````

````{py:function} _normalize_uploaded_archiveresult_plugin(plugin: str) -> str
:canonical: archivebox.api.v1_core._normalize_uploaded_archiveresult_plugin

```{autodoc2-docstring} archivebox.api.v1_core._normalize_uploaded_archiveresult_plugin
```
````

````{py:function} _normalize_uploaded_archiveresult_output_path(output_path: str, *, filename: str) -> str
:canonical: archivebox.api.v1_core._normalize_uploaded_archiveresult_output_path

```{autodoc2-docstring} archivebox.api.v1_core._normalize_uploaded_archiveresult_output_path
```
````

````{py:function} _parse_archiveresult_output_json(output_json: str | None) -> dict[str, typing.Any] | None
:canonical: archivebox.api.v1_core._parse_archiveresult_output_json

```{autodoc2-docstring} archivebox.api.v1_core._parse_archiveresult_output_json
```
````

````{py:function} _get_archiveresult_upload_data(request: django.http.HttpRequest)
:canonical: archivebox.api.v1_core._get_archiveresult_upload_data

```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_data
```
````

````{py:function} _get_archiveresult_upload_files(request: django.http.HttpRequest, *, allow_empty: bool = False) -> list[ninja.UploadedFile]
:canonical: archivebox.api.v1_core._get_archiveresult_upload_files

```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_files
```
````

````{py:function} _get_archiveresult_upload_form_values(request: django.http.HttpRequest, *field_names: str) -> list[str]
:canonical: archivebox.api.v1_core._get_archiveresult_upload_form_values

```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_form_values
```
````

````{py:function} _get_archiveresult_upload_form_value(request: django.http.HttpRequest, *field_names: str) -> str
:canonical: archivebox.api.v1_core._get_archiveresult_upload_form_value

```{autodoc2-docstring} archivebox.api.v1_core._get_archiveresult_upload_form_value
```
````

````{py:function} _parse_archiveresult_upload_int(value: str, field_name: str, *, default: int | None = None) -> int
:canonical: archivebox.api.v1_core._parse_archiveresult_upload_int

```{autodoc2-docstring} archivebox.api.v1_core._parse_archiveresult_upload_int
```
````

````{py:function} _summarize_archiveresult_output_files(output_files: dict[str, dict[str, typing.Any]]) -> tuple[int, str]
:canonical: archivebox.api.v1_core._summarize_archiveresult_output_files

```{autodoc2-docstring} archivebox.api.v1_core._summarize_archiveresult_output_files
```
````

````{py:function} _get_snapshot_by_ref(snapshot_id: str)
:canonical: archivebox.api.v1_core._get_snapshot_by_ref

```{autodoc2-docstring} archivebox.api.v1_core._get_snapshot_by_ref
```
````

````{py:function} _queue_archiveresult_snapshot_maintenance(snapshot: archivebox.core.models.Snapshot) -> None
:canonical: archivebox.api.v1_core._queue_archiveresult_snapshot_maintenance

```{autodoc2-docstring} archivebox.api.v1_core._queue_archiveresult_snapshot_maintenance
```
````

````{py:function} _merge_archiveresult_output_file_maps(results: list[archivebox.core.models.ArchiveResult]) -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.api.v1_core._merge_archiveresult_output_file_maps

```{autodoc2-docstring} archivebox.api.v1_core._merge_archiveresult_output_file_maps
```
````

````{py:function} _write_archiveresult_files(request: django.http.HttpRequest, snapshot: archivebox.core.models.Snapshot, plugin_name: str, *, existing_output_files: dict[str, dict[str, typing.Any]] | None = None, allow_empty: bool = False) -> dict[str, dict[str, typing.Any]]
:canonical: archivebox.api.v1_core._write_archiveresult_files

```{autodoc2-docstring} archivebox.api.v1_core._write_archiveresult_files
```
````

````{py:function} create_archiveresult(request: django.http.HttpRequest, snapshot_id: str = Form(...), plugin: str = Form(...), output_str: str = Form(''), hook_name: str = Form(ARCHIVERESULT_UPLOAD_HOOK_NAME), status: str = Form(str(ArchiveResult.StatusChoices.SUCCEEDED)), output_json: str = Form(''))
:canonical: archivebox.api.v1_core.create_archiveresult

```{autodoc2-docstring} archivebox.api.v1_core.create_archiveresult
```
````

````{py:function} patch_archiveresult(request: django.http.HttpRequest, archiveresult_id: str)
:canonical: archivebox.api.v1_core.patch_archiveresult

```{autodoc2-docstring} archivebox.api.v1_core.patch_archiveresult
```
````

`````{py:class} SnapshotSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.SnapshotSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_core.SnapshotSchema.TYPE
:type: str
:value: >
   'core.models.Snapshot'

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_core.SnapshotSchema.id
:type: uuid.UUID
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.id
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_core.SnapshotSchema.created_by_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_core.SnapshotSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.created_by_username
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_core.SnapshotSchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_core.SnapshotSchema.modified_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.modified_at
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.SnapshotSchema.status
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.api.v1_core.SnapshotSchema.retry_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.retry_at
```

````

````{py:attribute} bookmarked_at
:canonical: archivebox.api.v1_core.SnapshotSchema.bookmarked_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.bookmarked_at
```

````

````{py:attribute} downloaded_at
:canonical: archivebox.api.v1_core.SnapshotSchema.downloaded_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.downloaded_at
```

````

````{py:attribute} url
:canonical: archivebox.api.v1_core.SnapshotSchema.url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.url
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_core.SnapshotSchema.tags
:type: list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.tags
```

````

````{py:attribute} title
:canonical: archivebox.api.v1_core.SnapshotSchema.title
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.title
```

````

````{py:attribute} timestamp
:canonical: archivebox.api.v1_core.SnapshotSchema.timestamp
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.timestamp
```

````

````{py:attribute} archive_path
:canonical: archivebox.api.v1_core.SnapshotSchema.archive_path
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.archive_path
```

````

````{py:attribute} archive_size
:canonical: archivebox.api.v1_core.SnapshotSchema.archive_size
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.archive_size
```

````

````{py:attribute} output_size
:canonical: archivebox.api.v1_core.SnapshotSchema.output_size
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.output_size
```

````

````{py:attribute} num_archiveresults
:canonical: archivebox.api.v1_core.SnapshotSchema.num_archiveresults
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.num_archiveresults
```

````

````{py:attribute} archiveresults
:canonical: archivebox.api.v1_core.SnapshotSchema.archiveresults
:type: list[archivebox.api.v1_core.MinimalArchiveResultSchema]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.archiveresults
```

````

````{py:method} resolve_created_by_id(obj)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_created_by_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_created_by_id
```

````

````{py:method} resolve_created_by_username(obj)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_created_by_username
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_created_by_username
```

````

````{py:method} resolve_tags(obj)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_tags
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_tags
```

````

````{py:method} resolve_archive_size(obj)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_archive_size
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_archive_size
```

````

````{py:method} resolve_output_size(obj)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_output_size
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_output_size
```

````

````{py:method} resolve_num_archiveresults(obj, context)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_num_archiveresults
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_num_archiveresults
```

````

````{py:method} resolve_archiveresults(obj, context)
:canonical: archivebox.api.v1_core.SnapshotSchema.resolve_archiveresults
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotSchema.resolve_archiveresults
```

````

`````

`````{py:class} SnapshotUpdateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.SnapshotUpdateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} action
:canonical: archivebox.api.v1_core.SnapshotUpdateSchema.action
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotUpdateSchema.action
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.SnapshotUpdateSchema.status
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotUpdateSchema.status
```

````

````{py:attribute} retry_at
:canonical: archivebox.api.v1_core.SnapshotUpdateSchema.retry_at
:type: datetime.datetime | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotUpdateSchema.retry_at
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_core.SnapshotUpdateSchema.tags
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotUpdateSchema.tags
```

````

`````

`````{py:class} SnapshotCreateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.SnapshotCreateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} url
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.url
```

````

````{py:attribute} crawl_id
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.crawl_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.crawl_id
```

````

````{py:attribute} depth
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.depth
:type: int
:value: >
   0

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.depth
```

````

````{py:attribute} title
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.title
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.title
```

````

````{py:attribute} tags
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.tags
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.tags
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.SnapshotCreateSchema.status
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotCreateSchema.status
```

````

`````

`````{py:class} SnapshotDeleteResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.SnapshotDeleteResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_core.SnapshotDeleteResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotDeleteResponseSchema.success
```

````

````{py:attribute} snapshot_id
:canonical: archivebox.api.v1_core.SnapshotDeleteResponseSchema.snapshot_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotDeleteResponseSchema.snapshot_id
```

````

````{py:attribute} crawl_id
:canonical: archivebox.api.v1_core.SnapshotDeleteResponseSchema.crawl_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotDeleteResponseSchema.crawl_id
```

````

````{py:attribute} deleted_count
:canonical: archivebox.api.v1_core.SnapshotDeleteResponseSchema.deleted_count
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotDeleteResponseSchema.deleted_count
```

````

`````

````{py:function} normalize_tag_list(tags: list[str] | None = None) -> list[str]
:canonical: archivebox.api.v1_core.normalize_tag_list

```{autodoc2-docstring} archivebox.api.v1_core.normalize_tag_list
```
````

````{py:function} _parse_rss_before(before: str | None) -> datetime.datetime
:canonical: archivebox.api.v1_core._parse_rss_before

```{autodoc2-docstring} archivebox.api.v1_core._parse_rss_before
```
````

````{py:function} _filter_snapshots_for_rss(*, crawl_id: str = '', created_by: str = '', before: str | None = None, limit: int = 50)
:canonical: archivebox.api.v1_core._filter_snapshots_for_rss

```{autodoc2-docstring} archivebox.api.v1_core._filter_snapshots_for_rss
```
````

````{py:function} _snapshots_rss_response(request: django.http.HttpRequest, *, snapshots, title: str = 'ArchiveBox Snapshots') -> django.http.HttpResponse
:canonical: archivebox.api.v1_core._snapshots_rss_response

```{autodoc2-docstring} archivebox.api.v1_core._snapshots_rss_response
```
````

`````{py:class} SnapshotFilterSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.SnapshotFilterSchema

Bases: {py:obj}`ninja.FilterSchema`

````{py:attribute} id
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.id
:type: typing.Annotated[str | None, FilterLookup(['id__istartswith', 'id__iendswith', 'timestamp__startswith'])]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.id
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.created_by_id
:type: typing.Annotated[str | None, FilterLookup('crawl__created_by_id')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.created_by_username
:type: typing.Annotated[str | None, FilterLookup('crawl__created_by__username__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.created_by_username
```

````

````{py:attribute} created_at__gte
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.created_at__gte
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at__gte')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.created_at__gte
```

````

````{py:attribute} created_at__lt
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.created_at__lt
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at__lt')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.created_at__lt
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.created_at
:type: typing.Annotated[datetime.datetime | None, FilterLookup('created_at')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.modified_at
:type: typing.Annotated[datetime.datetime | None, FilterLookup('modified_at')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.modified_at
```

````

````{py:attribute} modified_at__gte
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.modified_at__gte
:type: typing.Annotated[datetime.datetime | None, FilterLookup('modified_at__gte')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.modified_at__gte
```

````

````{py:attribute} modified_at__lt
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.modified_at__lt
:type: typing.Annotated[datetime.datetime | None, FilterLookup('modified_at__lt')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.modified_at__lt
```

````

````{py:attribute} search
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.search
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.search
```

````

````{py:attribute} search_mode
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.search_mode
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.search_mode
```

````

````{py:attribute} status
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.status
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.status
```

````

````{py:attribute} url
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.url
:type: typing.Annotated[str | None, FilterLookup('url')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.url
```

````

````{py:attribute} tag
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.tag
:type: typing.Annotated[str | None, FilterLookup('tags__name')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.tag
```

````

````{py:attribute} title
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.title
:type: typing.Annotated[str | None, FilterLookup('title__icontains')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.title
```

````

````{py:attribute} timestamp
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.timestamp
:type: typing.Annotated[str | None, FilterLookup('timestamp__startswith')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.timestamp
```

````

````{py:attribute} bookmarked_at__gte
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.bookmarked_at__gte
:type: typing.Annotated[datetime.datetime | None, FilterLookup('bookmarked_at__gte')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.bookmarked_at__gte
```

````

````{py:attribute} bookmarked_at__lt
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.bookmarked_at__lt
:type: typing.Annotated[datetime.datetime | None, FilterLookup('bookmarked_at__lt')]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.bookmarked_at__lt
```

````

````{py:method} filter_search(value: str | None) -> django.db.models.Q
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.filter_search

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.filter_search
```

````

````{py:method} filter_search_mode(value: str | None) -> django.db.models.Q
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.filter_search_mode

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.filter_search_mode
```

````

````{py:method} filter_status(value: str | None) -> django.db.models.Q
:canonical: archivebox.api.v1_core.SnapshotFilterSchema.filter_status

```{autodoc2-docstring} archivebox.api.v1_core.SnapshotFilterSchema.filter_status
```

````

`````

````{py:function} get_snapshots(request: django.http.HttpRequest, filters: ninja.Query[archivebox.api.v1_core.SnapshotFilterSchema], with_archiveresults: bool = False)
:canonical: archivebox.api.v1_core.get_snapshots

```{autodoc2-docstring} archivebox.api.v1_core.get_snapshots
```
````

````{py:function} get_snapshots_rss(request: django.http.HttpRequest, crawl_id: str = '', created_by: str = '', limit: int = 50, before: str | None = None)
:canonical: archivebox.api.v1_core.get_snapshots_rss

```{autodoc2-docstring} archivebox.api.v1_core.get_snapshots_rss
```
````

````{py:function} get_snapshot(request: django.http.HttpRequest, snapshot_id: str, with_archiveresults: bool = True)
:canonical: archivebox.api.v1_core.get_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.get_snapshot
```
````

````{py:function} create_snapshot(request: django.http.HttpRequest, data: archivebox.api.v1_core.SnapshotCreateSchema)
:canonical: archivebox.api.v1_core.create_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.create_snapshot
```
````

````{py:function} patch_snapshot(request: django.http.HttpRequest, snapshot_id: str, data: archivebox.api.v1_core.SnapshotUpdateSchema)
:canonical: archivebox.api.v1_core.patch_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.patch_snapshot
```
````

````{py:function} delete_snapshot(request: django.http.HttpRequest, snapshot_id: str)
:canonical: archivebox.api.v1_core.delete_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.delete_snapshot
```
````

`````{py:class} TagSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} TYPE
:canonical: archivebox.api.v1_core.TagSchema.TYPE
:type: str
:value: >
   'core.models.Tag'

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.TYPE
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_core.TagSchema.id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.id
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.v1_core.TagSchema.modified_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.modified_at
```

````

````{py:attribute} created_at
:canonical: archivebox.api.v1_core.TagSchema.created_at
:type: datetime.datetime
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.created_at
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_core.TagSchema.created_by_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_core.TagSchema.created_by_username
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.created_by_username
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_core.TagSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.name
```

````

````{py:attribute} num_snapshots
:canonical: archivebox.api.v1_core.TagSchema.num_snapshots
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.num_snapshots
```

````

````{py:attribute} snapshots
:canonical: archivebox.api.v1_core.TagSchema.snapshots
:type: list[archivebox.api.v1_core.SnapshotSchema]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.snapshots
```

````

````{py:method} resolve_created_by_id(obj)
:canonical: archivebox.api.v1_core.TagSchema.resolve_created_by_id
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.resolve_created_by_id
```

````

````{py:method} resolve_created_by_username(obj)
:canonical: archivebox.api.v1_core.TagSchema.resolve_created_by_username
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.resolve_created_by_username
```

````

````{py:method} resolve_num_snapshots(obj, context)
:canonical: archivebox.api.v1_core.TagSchema.resolve_num_snapshots
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.resolve_num_snapshots
```

````

````{py:method} resolve_snapshots(obj, context)
:canonical: archivebox.api.v1_core.TagSchema.resolve_snapshots
:staticmethod:

```{autodoc2-docstring} archivebox.api.v1_core.TagSchema.resolve_snapshots
```

````

`````

````{py:function} get_tags(request: django.http.HttpRequest)
:canonical: archivebox.api.v1_core.get_tags

```{autodoc2-docstring} archivebox.api.v1_core.get_tags
```
````

````{py:function} get_tag(request: django.http.HttpRequest, tag_id: str, with_snapshots: bool = True)
:canonical: archivebox.api.v1_core.get_tag

```{autodoc2-docstring} archivebox.api.v1_core.get_tag
```
````

````{py:function} get_any(request: django.http.HttpRequest, id: str)
:canonical: archivebox.api.v1_core.get_any

```{autodoc2-docstring} archivebox.api.v1_core.get_any
```
````

`````{py:class} TagAutocompleteSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagAutocompleteSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} tags
:canonical: archivebox.api.v1_core.TagAutocompleteSchema.tags
:type: list[dict]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagAutocompleteSchema.tags
```

````

`````

`````{py:class} TagCreateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagCreateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} name
:canonical: archivebox.api.v1_core.TagCreateSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagCreateSchema.name
```

````

`````

`````{py:class} TagCreateResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagCreateResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_core.TagCreateResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagCreateResponseSchema.success
```

````

````{py:attribute} tag_id
:canonical: archivebox.api.v1_core.TagCreateResponseSchema.tag_id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagCreateResponseSchema.tag_id
```

````

````{py:attribute} tag_name
:canonical: archivebox.api.v1_core.TagCreateResponseSchema.tag_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagCreateResponseSchema.tag_name
```

````

````{py:attribute} created
:canonical: archivebox.api.v1_core.TagCreateResponseSchema.created
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagCreateResponseSchema.created
```

````

`````

`````{py:class} TagSearchSnapshotSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} id
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.id
```

````

````{py:attribute} title
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.title
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.title
```

````

````{py:attribute} url
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.url
```

````

````{py:attribute} favicon_url
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.favicon_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.favicon_url
```

````

````{py:attribute} admin_url
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.admin_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.admin_url
```

````

````{py:attribute} archive_url
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.archive_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.archive_url
```

````

````{py:attribute} downloaded_at
:canonical: archivebox.api.v1_core.TagSearchSnapshotSchema.downloaded_at
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchSnapshotSchema.downloaded_at
```

````

`````

`````{py:class} TagSearchCardSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSearchCardSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} id
:canonical: archivebox.api.v1_core.TagSearchCardSchema.id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_core.TagSearchCardSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.name
```

````

````{py:attribute} slug
:canonical: archivebox.api.v1_core.TagSearchCardSchema.slug
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.slug
```

````

````{py:attribute} num_snapshots
:canonical: archivebox.api.v1_core.TagSearchCardSchema.num_snapshots
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.num_snapshots
```

````

````{py:attribute} filter_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.filter_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.filter_url
```

````

````{py:attribute} edit_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.edit_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.edit_url
```

````

````{py:attribute} export_urls_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.export_urls_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.export_urls_url
```

````

````{py:attribute} export_jsonl_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.export_jsonl_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.export_jsonl_url
```

````

````{py:attribute} rename_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.rename_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.rename_url
```

````

````{py:attribute} delete_url
:canonical: archivebox.api.v1_core.TagSearchCardSchema.delete_url
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.delete_url
```

````

````{py:attribute} snapshots
:canonical: archivebox.api.v1_core.TagSearchCardSchema.snapshots
:type: list[archivebox.api.v1_core.TagSearchSnapshotSchema]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchCardSchema.snapshots
```

````

`````

`````{py:class} TagSearchResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSearchResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} tags
:canonical: archivebox.api.v1_core.TagSearchResponseSchema.tags
:type: list[archivebox.api.v1_core.TagSearchCardSchema]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchResponseSchema.tags
```

````

````{py:attribute} sort
:canonical: archivebox.api.v1_core.TagSearchResponseSchema.sort
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchResponseSchema.sort
```

````

````{py:attribute} created_by
:canonical: archivebox.api.v1_core.TagSearchResponseSchema.created_by
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchResponseSchema.created_by
```

````

````{py:attribute} year
:canonical: archivebox.api.v1_core.TagSearchResponseSchema.year
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchResponseSchema.year
```

````

````{py:attribute} has_snapshots
:canonical: archivebox.api.v1_core.TagSearchResponseSchema.has_snapshots
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSearchResponseSchema.has_snapshots
```

````

`````

`````{py:class} TagUpdateSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagUpdateSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} name
:canonical: archivebox.api.v1_core.TagUpdateSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagUpdateSchema.name
```

````

`````

`````{py:class} TagUpdateResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagUpdateResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_core.TagUpdateResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagUpdateResponseSchema.success
```

````

````{py:attribute} tag_id
:canonical: archivebox.api.v1_core.TagUpdateResponseSchema.tag_id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagUpdateResponseSchema.tag_id
```

````

````{py:attribute} tag_name
:canonical: archivebox.api.v1_core.TagUpdateResponseSchema.tag_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagUpdateResponseSchema.tag_name
```

````

`````

`````{py:class} TagDeleteResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagDeleteResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_core.TagDeleteResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagDeleteResponseSchema.success
```

````

````{py:attribute} tag_id
:canonical: archivebox.api.v1_core.TagDeleteResponseSchema.tag_id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagDeleteResponseSchema.tag_id
```

````

````{py:attribute} deleted_count
:canonical: archivebox.api.v1_core.TagDeleteResponseSchema.deleted_count
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagDeleteResponseSchema.deleted_count
```

````

`````

`````{py:class} TagSnapshotRequestSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSnapshotRequestSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} snapshot_id
:canonical: archivebox.api.v1_core.TagSnapshotRequestSchema.snapshot_id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotRequestSchema.snapshot_id
```

````

````{py:attribute} tag_name
:canonical: archivebox.api.v1_core.TagSnapshotRequestSchema.tag_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotRequestSchema.tag_name
```

````

````{py:attribute} tag_id
:canonical: archivebox.api.v1_core.TagSnapshotRequestSchema.tag_id
:type: int | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotRequestSchema.tag_id
```

````

`````

`````{py:class} TagSnapshotResponseSchema(/, **data: typing.Any)
:canonical: archivebox.api.v1_core.TagSnapshotResponseSchema

Bases: {py:obj}`ninja.Schema`

````{py:attribute} success
:canonical: archivebox.api.v1_core.TagSnapshotResponseSchema.success
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotResponseSchema.success
```

````

````{py:attribute} tag_id
:canonical: archivebox.api.v1_core.TagSnapshotResponseSchema.tag_id
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotResponseSchema.tag_id
```

````

````{py:attribute} tag_name
:canonical: archivebox.api.v1_core.TagSnapshotResponseSchema.tag_name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_core.TagSnapshotResponseSchema.tag_name
```

````

`````

````{py:function} _get_snapshot_for_tag_edit(snapshot_ref: str) -> archivebox.core.models.Snapshot
:canonical: archivebox.api.v1_core._get_snapshot_for_tag_edit

```{autodoc2-docstring} archivebox.api.v1_core._get_snapshot_for_tag_edit
```
````

````{py:function} search_tags(request: django.http.HttpRequest, q: str = '', sort: str = 'created_desc', created_by: str = '', year: str = '', has_snapshots: str = 'all')
:canonical: archivebox.api.v1_core.search_tags

```{autodoc2-docstring} archivebox.api.v1_core.search_tags
```
````

````{py:function} _public_tag_listing_enabled() -> bool
:canonical: archivebox.api.v1_core._public_tag_listing_enabled

```{autodoc2-docstring} archivebox.api.v1_core._public_tag_listing_enabled
```
````

````{py:function} _request_has_tag_autocomplete_access(request: django.http.HttpRequest) -> bool
:canonical: archivebox.api.v1_core._request_has_tag_autocomplete_access

```{autodoc2-docstring} archivebox.api.v1_core._request_has_tag_autocomplete_access
```
````

````{py:function} tags_autocomplete(request: django.http.HttpRequest, q: str = '')
:canonical: archivebox.api.v1_core.tags_autocomplete

```{autodoc2-docstring} archivebox.api.v1_core.tags_autocomplete
```
````

````{py:function} tags_create(request: django.http.HttpRequest, data: archivebox.api.v1_core.TagCreateSchema)
:canonical: archivebox.api.v1_core.tags_create

```{autodoc2-docstring} archivebox.api.v1_core.tags_create
```
````

````{py:function} rename_tag(request: django.http.HttpRequest, tag_id: int, data: archivebox.api.v1_core.TagUpdateSchema)
:canonical: archivebox.api.v1_core.rename_tag

```{autodoc2-docstring} archivebox.api.v1_core.rename_tag
```
````

````{py:function} delete_tag(request: django.http.HttpRequest, tag_id: int)
:canonical: archivebox.api.v1_core.delete_tag

```{autodoc2-docstring} archivebox.api.v1_core.delete_tag
```
````

````{py:function} tag_urls_export(request: django.http.HttpRequest, tag_id: int)
:canonical: archivebox.api.v1_core.tag_urls_export

```{autodoc2-docstring} archivebox.api.v1_core.tag_urls_export
```
````

````{py:function} tag_snapshots_export(request: django.http.HttpRequest, tag_id: int)
:canonical: archivebox.api.v1_core.tag_snapshots_export

```{autodoc2-docstring} archivebox.api.v1_core.tag_snapshots_export
```
````

````{py:function} tags_add_to_snapshot(request: django.http.HttpRequest, data: archivebox.api.v1_core.TagSnapshotRequestSchema)
:canonical: archivebox.api.v1_core.tags_add_to_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.tags_add_to_snapshot
```
````

````{py:function} tags_remove_from_snapshot(request: django.http.HttpRequest, data: archivebox.api.v1_core.TagSnapshotRequestSchema)
:canonical: archivebox.api.v1_core.tags_remove_from_snapshot

```{autodoc2-docstring} archivebox.api.v1_core.tags_remove_from_snapshot
```
````
