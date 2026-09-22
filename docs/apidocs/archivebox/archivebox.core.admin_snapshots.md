# {py:mod}`archivebox.core.admin_snapshots`

```{py:module} archivebox.core.admin_snapshots
```

```{autodoc2-docstring} archivebox.core.admin_snapshots
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SnapshotActionForm <archivebox.core.admin_snapshots.SnapshotActionForm>`
  -
* - {py:obj}`TagNameListFilter <archivebox.core.admin_snapshots.TagNameListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter
    :summary:
    ```
* - {py:obj}`SnapshotPermissionsListFilter <archivebox.core.admin_snapshots.SnapshotPermissionsListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter
    :summary:
    ```
* - {py:obj}`SnapshotStatusListFilter <archivebox.core.admin_snapshots.SnapshotStatusListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter
    :summary:
    ```
* - {py:obj}`SnapshotArchiveStateListFilter <archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter
    :summary:
    ```
* - {py:obj}`SnapshotSizeListFilter <archivebox.core.admin_snapshots.SnapshotSizeListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter
    :summary:
    ```
* - {py:obj}`SnapshotResultHealthListFilter <archivebox.core.admin_snapshots.SnapshotResultHealthListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter
    :summary:
    ```
* - {py:obj}`SnapshotChangeList <archivebox.core.admin_snapshots.SnapshotChangeList>`
  -
* - {py:obj}`SnapshotAdminForm <archivebox.core.admin_snapshots.SnapshotAdminForm>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm
    :summary:
    ```
* - {py:obj}`SnapshotAdmin <archivebox.core.admin_snapshots.SnapshotAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_plugin_sort_order <archivebox.core.admin_snapshots._plugin_sort_order>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots._plugin_sort_order
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`GLOBAL_CONTEXT <archivebox.core.admin_snapshots.GLOBAL_CONTEXT>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.GLOBAL_CONTEXT
    :summary:
    ```
* - {py:obj}`SNAPSHOT_PERMISSION_META <archivebox.core.admin_snapshots.SNAPSHOT_PERMISSION_META>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SNAPSHOT_PERMISSION_META
    :summary:
    ```
````

### API

````{py:data} GLOBAL_CONTEXT
:canonical: archivebox.core.admin_snapshots.GLOBAL_CONTEXT
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.GLOBAL_CONTEXT
```

````

````{py:data} SNAPSHOT_PERMISSION_META
:canonical: archivebox.core.admin_snapshots.SNAPSHOT_PERMISSION_META
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SNAPSHOT_PERMISSION_META
```

````

````{py:function} _plugin_sort_order() -> dict[str, int]
:canonical: archivebox.core.admin_snapshots._plugin_sort_order

```{autodoc2-docstring} archivebox.core.admin_snapshots._plugin_sort_order
```
````

`````{py:class} SnapshotActionForm(*args, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotActionForm

Bases: {py:obj}`django.contrib.admin.helpers.ActionForm`

````{py:method} clean_tags()
:canonical: archivebox.core.admin_snapshots.SnapshotActionForm.clean_tags

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotActionForm.clean_tags
```

````

`````

`````{py:class} TagNameListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.TagNameListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.TagNameListFilter.title
:value: >
   'By tag name'

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.TagNameListFilter.parameter_name
:value: >
   'tag'

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.TagNameListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.TagNameListFilter.queryset

````

`````

`````{py:class} SnapshotPermissionsListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.title
:value: >
   'permission'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.parameter_name
:value: >
   'permissions'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.queryset

````

`````

`````{py:class} SnapshotStatusListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter.title
:value: >
   'snapshot status'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter.parameter_name
:value: >
   'snapshot_status'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter.queryset

````

`````

`````{py:class} SnapshotArchiveStateListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.title
:value: >
   'archive state'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.parameter_name
:value: >
   'archive_state'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.queryset

````

`````

`````{py:class} SnapshotSizeListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter.title
:value: >
   'size'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter.parameter_name
:value: >
   'size'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter.queryset

````

`````

`````{py:class} SnapshotResultHealthListFilter(request, params, model, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.title
:value: >
   'ArchiveResult status'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.parameter_name
:value: >
   'archiveresult_status'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.parameter_name
```

````

````{py:attribute} SNAPSHOT_FIRST_VALUES
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.SNAPSHOT_FIRST_VALUES
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.SNAPSHOT_FIRST_VALUES
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.queryset

````

`````

`````{py:class} SnapshotChangeList(request, *args, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotChangeList

Bases: {py:obj}`archivebox.search.admin.SearchResultsChangeList`

````{py:method} _attach_archiveresult_summaries()
:canonical: archivebox.core.admin_snapshots.SnapshotChangeList._attach_archiveresult_summaries

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotChangeList._attach_archiveresult_summaries
```

````

````{py:method} get_results(request)
:canonical: archivebox.core.admin_snapshots.SnapshotChangeList.get_results

````

`````

``````{py:class} SnapshotAdminForm(*args, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm

Bases: {py:obj}`django.forms.ModelForm`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.__init__
```

````{py:attribute} tags_editor
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.tags_editor
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.tags_editor
```

````

````{py:attribute} permissions_config
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.permissions_config
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.permissions_config
```

````

`````{py:class} Meta
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.Meta

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.Meta
```

````{py:attribute} model
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.Meta.fields
:value: >
   '__all__'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.Meta.fields
```

````

`````

````{py:method} save(commit=True)
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.save

````

``````

`````{py:class} SnapshotAdmin(model, admin_site)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin

Bases: {py:obj}`archivebox.search.admin.SearchResultsAdminMixin`, {py:obj}`archivebox.base_models.admin.ConfigEditorMixin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} form
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.form
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.form
```

````

````{py:attribute} raw_id_fields
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.raw_id_fields
:value: >
   ('crawl', 'parent_snapshot')

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.raw_id_fields
```

````

````{py:attribute} list_select_related
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_select_related
:value: >
   ()

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_select_related
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_display
:value: >
   ('permissions_badge', 'created_at', 'preview_icon', 'title_str', 'tags_inline', 'status_with_progres...

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_display
```

````

````{py:attribute} list_display_links
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_display_links
:value: >
   ('created_at',)

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_display_links
```

````

````{py:attribute} sort_fields
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.sort_fields
:value: >
   ('title_str', 'created_at', 'status', 'crawl')

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.readonly_fields
:value: >
   ('admin_actions', 'snapshot_summary', 'url_favicon', 'tags_badges', 'imported_timestamp', 'created_a...

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.readonly_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.search_fields
:value: >
   ('id', 'url', 'timestamp', 'title', 'tags__name')

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.search_fields
```

````

````{py:attribute} list_filter
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_filter
:value: >
   ()

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_filter
```

````

````{py:attribute} fieldsets
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.fieldsets
:value: >
   (('Actions',), ('Snapshot',), ('URL',), ('Tags',), ('Status',), ('Timestamps',), ('Relations',), ('C...

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.fieldsets
```

````

````{py:attribute} ordering
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.ordering
```

````

````{py:attribute} actions
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.actions
:value: >
   ['add_tags', 'remove_tags', 'resnapshot_snapshot', 'update_snapshots', 'overwrite_snapshots', 'set_s...

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.actions
```

````

````{py:attribute} inlines
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.inlines
:value: >
   []

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.inlines
```

````

````{py:attribute} list_per_page
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_per_page
:value: >
   50

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_per_page
```

````

````{py:attribute} action_form
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.action_form
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.action_form
```

````

````{py:attribute} paginator
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.paginator
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.paginator
```

````

````{py:attribute} save_on_top
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.save_on_top
:value: >
   True

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.save_on_top
```

````

````{py:attribute} show_full_result_count
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.show_full_result_count
:value: >
   True

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.show_full_result_count
```

````

````{py:method} get_changelist(request, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_changelist

````

````{py:method} get_ordering(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_ordering

````

````{py:method} change_view(request, object_id, form_url='', extra_context=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.change_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.change_view
```

````

````{py:method} changelist_view(request, extra_context=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.changelist_view

````

````{py:method} get_actions(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_actions

````

````{py:method} lookup_allowed(lookup, value, request=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.lookup_allowed

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.lookup_allowed
```

````

````{py:method} get_snapshot_view_url(obj: archivebox.core.models.Snapshot) -> str
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_view_url

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_view_url
```

````

````{py:method} get_snapshot_files_url(obj: archivebox.core.models.Snapshot) -> str
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_files_url

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_files_url
```

````

````{py:method} get_snapshot_zip_url(obj: archivebox.core.models.Snapshot) -> str
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_zip_url

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_snapshot_zip_url
```

````

````{py:method} get_urls()
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_urls

````

````{py:method} search_stream_view(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.search_stream_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.search_stream_view
```

````

````{py:method} set_permissions_view(request, object_id)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.set_permissions_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.set_permissions_view
```

````

````{py:method} set_snapshot_permissions(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.set_snapshot_permissions

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.set_snapshot_permissions
```

````

````{py:method} update_snapshot_permissions(queryset, permissions)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.update_snapshot_permissions

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.update_snapshot_permissions
```

````

````{py:method} redo_failed_view(request, object_id)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.redo_failed_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.redo_failed_view
```

````

````{py:method} get_queryset(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_queryset

````

````{py:method} permissions_badge(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.permissions_badge

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.permissions_badge
```

````

````{py:method} imported_timestamp(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.imported_timestamp

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.imported_timestamp
```

````

````{py:method} admin_actions(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.admin_actions

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.admin_actions
```

````

````{py:method} status_info(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.status_info

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.status_info
```

````

````{py:method} archiveresults_list(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.archiveresults_list

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.archiveresults_list
```

````

````{py:method} title_str(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.title_str

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.title_str
```

````

````{py:method} tags_inline(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.tags_inline

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.tags_inline
```

````

````{py:method} tags_badges(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.tags_badges

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.tags_badges
```

````

````{py:method} _get_preview_data(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_preview_data

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_preview_data
```

````

````{py:method} url_favicon(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.url_favicon

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.url_favicon
```

````

````{py:method} preview_icon(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.preview_icon

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.preview_icon
```

````

````{py:method} snapshot_summary(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.snapshot_summary

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.snapshot_summary
```

````

````{py:method} files(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.files

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.files
```

````

````{py:method} size(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.size

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.size
```

````

````{py:method} status_with_progress(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.status_with_progress

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.status_with_progress
```

````

````{py:method} size_with_stats(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.size_with_stats

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.size_with_stats
```

````

````{py:method} _get_progress_stats(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_progress_stats

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_progress_stats
```

````

````{py:method} _get_prefetched_results(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_prefetched_results

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_prefetched_results
```

````

````{py:method} _get_expected_hook_total(obj) -> int
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_expected_hook_total

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_expected_hook_total
```

````

````{py:method} _get_prefetched_tags(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_prefetched_tags

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_prefetched_tags
```

````

````{py:method} _get_ordering_fields(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_ordering_fields

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_ordering_fields
```

````

````{py:method} url_str(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.url_str

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.url_str
```

````

````{py:method} health_display(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.health_display

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.health_display
```

````

````{py:method} grid_view(request, extra_context=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.grid_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.grid_view
```

````

````{py:method} update_snapshots(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.update_snapshots

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.update_snapshots
```

````

````{py:method} resnapshot_snapshot(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.resnapshot_snapshot

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.resnapshot_snapshot
```

````

````{py:method} overwrite_snapshots(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.overwrite_snapshots

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.overwrite_snapshots
```

````

````{py:method} delete_snapshots(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.delete_snapshots

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.delete_snapshots
```

````

````{py:method} add_tags(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.add_tags

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.add_tags
```

````

````{py:method} remove_tags(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.remove_tags

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.remove_tags
```

````

`````
