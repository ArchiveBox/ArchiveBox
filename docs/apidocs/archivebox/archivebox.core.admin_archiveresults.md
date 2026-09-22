# {py:mod}`archivebox.core.admin_archiveresults`

```{py:module} archivebox.core.admin_archiveresults
```

```{autodoc2-docstring} archivebox.core.admin_archiveresults
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveResultInline <archivebox.core.admin_archiveresults.ArchiveResultInline>`
  -
* - {py:obj}`ArchiveResultAdmin <archivebox.core.admin_archiveresults.ArchiveResultAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_get_replay_source_url <archivebox.core.admin_archiveresults._get_replay_source_url>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults._get_replay_source_url
    :summary:
    ```
* - {py:obj}`build_abx_dl_display_command <archivebox.core.admin_archiveresults.build_abx_dl_display_command>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.build_abx_dl_display_command
    :summary:
    ```
* - {py:obj}`build_abx_dl_replay_command <archivebox.core.admin_archiveresults.build_abx_dl_replay_command>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.build_abx_dl_replay_command
    :summary:
    ```
* - {py:obj}`get_plugin_admin_url <archivebox.core.admin_archiveresults.get_plugin_admin_url>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.get_plugin_admin_url
    :summary:
    ```
* - {py:obj}`get_process_link_label <archivebox.core.admin_archiveresults.get_process_link_label>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.get_process_link_label
    :summary:
    ```
* - {py:obj}`render_archiveresults_list <archivebox.core.admin_archiveresults.render_archiveresults_list>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.render_archiveresults_list
    :summary:
    ```
* - {py:obj}`register_admin <archivebox.core.admin_archiveresults.register_admin>`
  - ```{autodoc2-docstring} archivebox.core.admin_archiveresults.register_admin
    :summary:
    ```
````

### API

````{py:function} _get_replay_source_url(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults._get_replay_source_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults._get_replay_source_url
```
````

````{py:function} build_abx_dl_display_command(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults.build_abx_dl_display_command

```{autodoc2-docstring} archivebox.core.admin_archiveresults.build_abx_dl_display_command
```
````

````{py:function} build_abx_dl_replay_command(result: archivebox.core.models.ArchiveResult, config=None) -> str
:canonical: archivebox.core.admin_archiveresults.build_abx_dl_replay_command

```{autodoc2-docstring} archivebox.core.admin_archiveresults.build_abx_dl_replay_command
```
````

````{py:function} get_plugin_admin_url(plugin_name: str) -> str
:canonical: archivebox.core.admin_archiveresults.get_plugin_admin_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults.get_plugin_admin_url
```
````

````{py:function} get_process_link_label(process) -> str
:canonical: archivebox.core.admin_archiveresults.get_process_link_label

```{autodoc2-docstring} archivebox.core.admin_archiveresults.get_process_link_label
```
````

````{py:function} render_archiveresults_list(archiveresults_qs, limit=50, config=None)
:canonical: archivebox.core.admin_archiveresults.render_archiveresults_list

```{autodoc2-docstring} archivebox.core.admin_archiveresults.render_archiveresults_list
```
````

`````{py:class} ArchiveResultInline(parent_model, admin_site)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline

Bases: {py:obj}`django.contrib.admin.TabularInline`

````{py:attribute} name
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.name
:value: >
   'Archive Results Log'

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.name
```

````

````{py:attribute} model
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.model
```

````

````{py:attribute} parent_model
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.parent_model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.parent_model
```

````

````{py:attribute} extra
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.extra
:value: >
   0

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.extra
```

````

````{py:attribute} sort_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.sort_fields
:value: >
   ('end_ts', 'plugin', 'output_str', 'status', 'cmd_version')

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.readonly_fields
:value: >
   ('id', 'result_id', 'completed', 'command', 'version')

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.readonly_fields
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.fields
:value: >
   ('start_ts', 'end_ts')

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.fields
```

````

````{py:attribute} ordering
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.ordering
:value: >
   ('end_ts',)

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.ordering
```

````

````{py:attribute} show_change_link
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.show_change_link
:value: >
   True

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.show_change_link
```

````

````{py:method} get_parent_object_from_request(request)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.get_parent_object_from_request

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.get_parent_object_from_request
```

````

````{py:method} completed(obj)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.completed

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.completed
```

````

````{py:method} result_id(obj)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.result_id

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.result_id
```

````

````{py:method} command(obj)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.command

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.command
```

````

````{py:method} version(obj)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.version

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultInline.version
```

````

````{py:method} get_formset(request, obj=None, **kwargs)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.get_formset

````

````{py:method} get_readonly_fields(request, obj=None)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultInline.get_readonly_fields

````

`````

``````{py:class} ArchiveResultAdmin(model, admin_site)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_select_related
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_select_related
:value: >
   ()

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_select_related
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_display
:value: >
   ('details_link', 'zip_link', 'created_at', 'snapshot_info', 'tags_inline', 'status_badge', 'plugin_w...

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_display
```

````

````{py:attribute} list_display_links
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_display_links
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_display_links
```

````

````{py:attribute} sort_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.sort_fields
:value: >
   ('id', 'created_at', 'plugin', 'status')

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.readonly_fields
:value: >
   ('admin_actions', 'cmd', 'cmd_version', 'pwd', 'cmd_str', 'snapshot_info', 'tags_str', 'created_at',...

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.readonly_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.search_fields
:value: >
   ('snapshot__id', 'snapshot__url', 'snapshot__tags__name', 'snapshot__crawl_id', 'plugin', 'hook_name...

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.search_fields
```

````

````{py:attribute} autocomplete_fields
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.autocomplete_fields
:value: >
   ['snapshot']

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.autocomplete_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.fieldsets
:value: >
   (('Actions',), ('Snapshot',), ('Plugin',), ('Timing',), ('Command',), ('Output',))

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_filter
:value: >
   ('status', 'plugin', 'start_ts')

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.ordering
:value: >
   ['-start_ts']

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_per_page
:value: >
   50

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.list_per_page
```

````

````{py:attribute} paginator
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.paginator
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.paginator
```

````

````{py:attribute} save_on_top
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.save_on_top
:value: >
   True

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.save_on_top
```

````

````{py:attribute} show_full_result_count
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.show_full_result_count
:value: >
   False

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.show_full_result_count
```

````

````{py:attribute} actions
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.actions
```

````

`````{py:class} Meta
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta
```

````{py:attribute} verbose_name
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta.verbose_name
:value: >
   'Archive Result'

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta.verbose_name_plural
:value: >
   'Archive Results'

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.Meta.verbose_name_plural
```

````

`````

````{py:method} change_view(request, object_id, form_url='', extra_context=None)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.change_view

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.change_view
```

````

````{py:method} changelist_view(request, extra_context=None)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.changelist_view

````

````{py:method} get_queryset(request)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_queryset

````

````{py:method} get_search_results(request, queryset, search_term)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_search_results

````

````{py:method} get_snapshot_view_url(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_snapshot_view_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_snapshot_view_url
```

````

````{py:method} get_output_view_url(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_view_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_view_url
```

````

````{py:method} get_output_files_url(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_files_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_files_url
```

````

````{py:method} get_output_zip_url(result: archivebox.core.models.ArchiveResult) -> str
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_zip_url

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.get_output_zip_url
```

````

````{py:method} details_link(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.details_link

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.details_link
```

````

````{py:method} zip_link(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.zip_link

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.zip_link
```

````

````{py:method} snapshot_info(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.snapshot_info

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.snapshot_info
```

````

````{py:method} tags_str(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.tags_str

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.tags_str
```

````

````{py:method} tags_inline(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.tags_inline

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.tags_inline
```

````

````{py:method} status_badge(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.status_badge

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.status_badge
```

````

````{py:method} plugin_with_icon(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.plugin_with_icon

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.plugin_with_icon
```

````

````{py:method} process_link(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.process_link

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.process_link
```

````

````{py:method} machine_link(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.machine_link

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.machine_link
```

````

````{py:method} cmd_str(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.cmd_str

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.cmd_str
```

````

````{py:method} output_display(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_display

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_display
```

````

````{py:method} output_str_display(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_str_display

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_str_display
```

````

````{py:method} admin_actions(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.admin_actions

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.admin_actions
```

````

````{py:method} output_summary(result)
:canonical: archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_summary

```{autodoc2-docstring} archivebox.core.admin_archiveresults.ArchiveResultAdmin.output_summary
```

````

``````

````{py:function} register_admin(admin_site)
:canonical: archivebox.core.admin_archiveresults.register_admin

```{autodoc2-docstring} archivebox.core.admin_archiveresults.register_admin
```
````
