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
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotActionForm
    :summary:
    ```
* - {py:obj}`SnapshotDomainListFilter <archivebox.core.admin_snapshots.SnapshotDomainListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter
    :summary:
    ```
* - {py:obj}`SnapshotFolderListFilter <archivebox.core.admin_snapshots.SnapshotFolderListFilter>`
  - ```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter
    :summary:
    ```
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

`````{py:class} SnapshotActionForm(*args, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotActionForm

Bases: {py:obj}`django.contrib.admin.helpers.ActionForm`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotActionForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotActionForm.__init__
```

````{py:method} clean_tags()
:canonical: archivebox.core.admin_snapshots.SnapshotActionForm.clean_tags

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotActionForm.clean_tags
```

````

`````

`````{py:class} SnapshotDomainListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotDomainListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotDomainListFilter.title
:value: >
   'domain'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotDomainListFilter.parameter_name
:value: >
   'domain'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotDomainListFilter.lookups

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotDomainListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotDomainListFilter.queryset
```

````

`````

`````{py:class} SnapshotFolderListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotFolderListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter
```

````{py:attribute} title
:canonical: archivebox.core.admin_snapshots.SnapshotFolderListFilter.title
:value: >
   'folder'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.core.admin_snapshots.SnapshotFolderListFilter.parameter_name
:value: >
   'folder'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotFolderListFilter.lookups

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotFolderListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotFolderListFilter.queryset
```

````

`````

`````{py:class} TagNameListFilter
:canonical: archivebox.core.admin_snapshots.TagNameListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter
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

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.TagNameListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.TagNameListFilter.queryset
```

````

`````

`````{py:class} SnapshotPermissionsListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter
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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotPermissionsListFilter.queryset
```

````

`````

`````{py:class} SnapshotStatusListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter
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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotStatusListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotStatusListFilter.queryset
```

````

`````

`````{py:class} SnapshotArchiveStateListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter
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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotArchiveStateListFilter.queryset
```

````

`````

`````{py:class} SnapshotSizeListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter
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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotSizeListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotSizeListFilter.queryset
```

````

`````

`````{py:class} SnapshotResultHealthListFilter
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter
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

````{py:method} lookups(request, model_admin)
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.lookups

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.lookups
```

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.queryset

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotResultHealthListFilter.queryset
```

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

````{py:attribute} url
:canonical: archivebox.core.admin_snapshots.SnapshotAdminForm.url
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.url
```

````

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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdminForm.save
```

````

``````

`````{py:class} SnapshotAdmin
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin

Bases: {py:obj}`archivebox.search.admin.SearchResultsAdminMixin`, {py:obj}`archivebox.base_models.admin.ConfigEditorMixin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} change_list_template
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.change_list_template
:value: >
   'admin/core/snapshot/change_list.html'

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.change_list_template
```

````

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

````{py:method} save_related(request, form, formsets, change)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.save_related

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.save_related
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_display
:value: >
   ('permissions_badge', 'created_at_display', 'preview_icon', 'title_str', 'tags_inline', 'status_with...

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.list_display
```

````

````{py:attribute} list_display_links
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.list_display_links
:value: >
   ('created_at_display',)

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
   ['move_to_folder', 'add_tags', 'remove_tags', 'resnapshot_snapshot', 'update_snapshots', 'overwrite_...

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

````{py:method} created_at_display(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.created_at_display

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.created_at_display
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
   False

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.show_full_result_count
```

````

````{py:method} get_changelist(request, **kwargs)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_changelist

````

````{py:method} get_ordering(request)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_ordering

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_ordering
```

````

````{py:method} changeform_view(request, object_id=None, form_url='', extra_context=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.changeform_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.changeform_view
```

````

````{py:method} render_change_form(request, context, add=False, change=False, form_url='', obj=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.render_change_form

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.render_change_form
```

````

````{py:method} render_embedded_changelist(request, scoped_params)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.render_embedded_changelist

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.render_embedded_changelist
```

````

````{py:method} changelist_view(request, extra_context=None)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.changelist_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.changelist_view
```

````

````{py:method} get_actions(request, action_location=ActionLocation.CHANGE_LIST)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.get_actions

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_actions
```

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

````{py:method} export_view(request, format='rss')
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.export_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.export_view
```

````

````{py:method} export_job_view(request, process_id, action='status')
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.export_job_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.export_job_view
```

````

````{py:method} move_to_folder(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.move_to_folder

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.move_to_folder
```

````

````{py:method} preview_view(request, object_id, plugin, filename)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.preview_view

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.preview_view
```

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

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.get_queryset
```

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

````{py:method} _get_favicon_data(obj)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._get_favicon_data

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._get_favicon_data
```

````

````{py:method} _render_thumbnail(obj, width='100px', height='100px')
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin._render_thumbnail

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin._render_thumbnail
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

````{py:method} delete_selected(request, queryset)
:canonical: archivebox.core.admin_snapshots.SnapshotAdmin.delete_selected

```{autodoc2-docstring} archivebox.core.admin_snapshots.SnapshotAdmin.delete_selected
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
