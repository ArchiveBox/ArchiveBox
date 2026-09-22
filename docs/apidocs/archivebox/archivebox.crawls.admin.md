# {py:mod}`archivebox.crawls.admin`

```{py:module} archivebox.crawls.admin
```

```{autodoc2-docstring} archivebox.crawls.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MaxDepthListFilter <archivebox.crawls.admin.MaxDepthListFilter>`
  - ```{autodoc2-docstring} archivebox.crawls.admin.MaxDepthListFilter
    :summary:
    ```
* - {py:obj}`URLFiltersField <archivebox.crawls.admin.URLFiltersField>`
  - ```{autodoc2-docstring} archivebox.crawls.admin.URLFiltersField
    :summary:
    ```
* - {py:obj}`CrawlAdminForm <archivebox.crawls.admin.CrawlAdminForm>`
  - ```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm
    :summary:
    ```
* - {py:obj}`CrawlAdmin <archivebox.crawls.admin.CrawlAdmin>`
  -
* - {py:obj}`CrawlScheduleAdmin <archivebox.crawls.admin.CrawlScheduleAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`render_snapshots_list <archivebox.crawls.admin.render_snapshots_list>`
  - ```{autodoc2-docstring} archivebox.crawls.admin.render_snapshots_list
    :summary:
    ```
* - {py:obj}`register_admin <archivebox.crawls.admin.register_admin>`
  - ```{autodoc2-docstring} archivebox.crawls.admin.register_admin
    :summary:
    ```
````

### API

`````{py:class} MaxDepthListFilter(request, params, model, model_admin)
:canonical: archivebox.crawls.admin.MaxDepthListFilter

Bases: {py:obj}`django.contrib.admin.SimpleListFilter`

```{autodoc2-docstring} archivebox.crawls.admin.MaxDepthListFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.crawls.admin.MaxDepthListFilter.__init__
```

````{py:attribute} title
:canonical: archivebox.crawls.admin.MaxDepthListFilter.title
:value: >
   'max depth'

```{autodoc2-docstring} archivebox.crawls.admin.MaxDepthListFilter.title
```

````

````{py:attribute} parameter_name
:canonical: archivebox.crawls.admin.MaxDepthListFilter.parameter_name
:value: >
   'max_depth'

```{autodoc2-docstring} archivebox.crawls.admin.MaxDepthListFilter.parameter_name
```

````

````{py:method} lookups(request, model_admin)
:canonical: archivebox.crawls.admin.MaxDepthListFilter.lookups

````

````{py:method} queryset(request, queryset)
:canonical: archivebox.crawls.admin.MaxDepthListFilter.queryset

````

`````

````{py:function} render_snapshots_list(snapshots_qs, request=None, crawl=None, page_size=50, prefix='snapshots')
:canonical: archivebox.crawls.admin.render_snapshots_list

```{autodoc2-docstring} archivebox.crawls.admin.render_snapshots_list
```
````

`````{py:class} URLFiltersField(*, required=True, widget=None, label=None, initial=None, help_text='', error_messages=None, show_hidden_initial=False, validators=(), localize=False, disabled=False, label_suffix=None, template_name=None, bound_field_class=None)
:canonical: archivebox.crawls.admin.URLFiltersField

Bases: {py:obj}`django.forms.Field`

```{autodoc2-docstring} archivebox.crawls.admin.URLFiltersField
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.crawls.admin.URLFiltersField.__init__
```

````{py:attribute} widget
:canonical: archivebox.crawls.admin.URLFiltersField.widget
:value: >
   'URLFiltersWidget(...)'

```{autodoc2-docstring} archivebox.crawls.admin.URLFiltersField.widget
```

````

````{py:method} to_python(value)
:canonical: archivebox.crawls.admin.URLFiltersField.to_python

```{autodoc2-docstring} archivebox.crawls.admin.URLFiltersField.to_python
```

````

`````

``````{py:class} CrawlAdminForm(*args, **kwargs)
:canonical: archivebox.crawls.admin.CrawlAdminForm

Bases: {py:obj}`django.forms.ModelForm`

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.__init__
```

````{py:attribute} tags_editor
:canonical: archivebox.crawls.admin.CrawlAdminForm.tags_editor
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.tags_editor
```

````

````{py:attribute} url_filters
:canonical: archivebox.crawls.admin.CrawlAdminForm.url_filters
:value: >
   'URLFiltersField(...)'

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.url_filters
```

````

`````{py:class} Meta
:canonical: archivebox.crawls.admin.CrawlAdminForm.Meta

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.Meta
```

````{py:attribute} model
:canonical: archivebox.crawls.admin.CrawlAdminForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.crawls.admin.CrawlAdminForm.Meta.fields
:value: >
   '__all__'

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.Meta.fields
```

````

````{py:attribute} widgets
:canonical: archivebox.crawls.admin.CrawlAdminForm.Meta.widgets
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.Meta.widgets
```

````

`````

````{py:method} extract_url_line(line)
:canonical: archivebox.crawls.admin.CrawlAdminForm.extract_url_line
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.extract_url_line
```

````

````{py:method} regex_escape(text)
:canonical: archivebox.crawls.admin.CrawlAdminForm.regex_escape
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.regex_escape
```

````

````{py:method} generated_host_allowlist(urls)
:canonical: archivebox.crawls.admin.CrawlAdminForm.generated_host_allowlist
:classmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.generated_host_allowlist
```

````

````{py:method} subpath_prefix(pathname)
:canonical: archivebox.crawls.admin.CrawlAdminForm.subpath_prefix
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.subpath_prefix
```

````

````{py:method} parsed_host_and_port(parsed)
:canonical: archivebox.crawls.admin.CrawlAdminForm.parsed_host_and_port
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.parsed_host_and_port
```

````

````{py:method} generated_subpath_allowlist(urls)
:canonical: archivebox.crawls.admin.CrawlAdminForm.generated_subpath_allowlist
:classmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.generated_subpath_allowlist
```

````

````{py:method} derive_filter_toggles(urls, allowlist)
:canonical: archivebox.crawls.admin.CrawlAdminForm.derive_filter_toggles
:classmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.derive_filter_toggles
```

````

````{py:method} effective_only_new(crawl=None)
:canonical: archivebox.crawls.admin.CrawlAdminForm.effective_only_new
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.effective_only_new
```

````

````{py:method} inherited_only_new(crawl)
:canonical: archivebox.crawls.admin.CrawlAdminForm.inherited_only_new
:staticmethod:

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.inherited_only_new
```

````

````{py:method} clean_tags_editor()
:canonical: archivebox.crawls.admin.CrawlAdminForm.clean_tags_editor

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.clean_tags_editor
```

````

````{py:method} clean_url_filters()
:canonical: archivebox.crawls.admin.CrawlAdminForm.clean_url_filters

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdminForm.clean_url_filters
```

````

````{py:method} save(commit=True)
:canonical: archivebox.crawls.admin.CrawlAdminForm.save

````

``````

``````{py:class} CrawlAdmin(model, admin_site)
:canonical: archivebox.crawls.admin.CrawlAdmin

Bases: {py:obj}`archivebox.base_models.admin.ConfigEditorMixin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} form
:canonical: archivebox.crawls.admin.CrawlAdmin.form
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.form
```

````

````{py:attribute} change_form_template
:canonical: archivebox.crawls.admin.CrawlAdmin.change_form_template
:value: >
   'admin/crawls/crawl/change_form.html'

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.change_form_template
```

````

````{py:attribute} list_select_related
:canonical: archivebox.crawls.admin.CrawlAdmin.list_select_related
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.list_select_related
```

````

````{py:attribute} paginator
:canonical: archivebox.crawls.admin.CrawlAdmin.paginator
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.paginator
```

````

````{py:attribute} show_full_result_count
:canonical: archivebox.crawls.admin.CrawlAdmin.show_full_result_count
:value: >
   False

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.show_full_result_count
```

````

````{py:attribute} list_display
:canonical: archivebox.crawls.admin.CrawlAdmin.list_display
:value: >
   ('short_id', 'permissions_badge', 'created_at', 'owner', 'depth', 'status_with_stop_reason', 'pause_...

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.crawls.admin.CrawlAdmin.sort_fields
:value: >
   ('id', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'schedule_str', 'status', 'retry_a...

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.sort_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.crawls.admin.CrawlAdmin.search_fields
:value: >
   ('id', 'created_by__username', 'max_depth', 'label', 'notes', 'schedule_id', 'status', 'urls')

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.crawls.admin.CrawlAdmin.readonly_fields
:value: >
   ('created_at', 'modified_at', 'stop_reason_display')

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.crawls.admin.CrawlAdmin.fieldsets
:value: >
   (('URLs',), ('Overview',), ('Config',))

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.fieldsets
```

````

````{py:attribute} add_fieldsets
:canonical: archivebox.crawls.admin.CrawlAdmin.add_fieldsets
:value: >
   (('URLs',), ('Overview',), ('Config',))

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.add_fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.crawls.admin.CrawlAdmin.list_filter
:value: >
   ()

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.crawls.admin.CrawlAdmin.ordering
:value: >
   ['-created_at', '-retry_at']

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.crawls.admin.CrawlAdmin.list_per_page
:value: >
   50

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.crawls.admin.CrawlAdmin.actions
:value: >
   ['pause_selected_crawls', 'resume_selected_crawls', 'seal_selected_crawls', 'delete_selected_batched...

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.actions
```

````

````{py:attribute} change_actions
:canonical: archivebox.crawls.admin.CrawlAdmin.change_actions
:value: >
   ['recrawl']

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.change_actions
```

````

`````{py:class} Media
:canonical: archivebox.crawls.admin.CrawlAdmin.Media

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.Media
```

````{py:attribute} css
:canonical: archivebox.crawls.admin.CrawlAdmin.Media.css
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.Media.css
```

````

````{py:attribute} js
:canonical: archivebox.crawls.admin.CrawlAdmin.Media.js
:value: >
   ('admin/crawls/crawl_admin.js',)

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.Media.js
```

````

`````

````{py:method} changelist_view(request, extra_context=None)
:canonical: archivebox.crawls.admin.CrawlAdmin.changelist_view

````

````{py:method} should_annotate_snapshot_counts(request)
:canonical: archivebox.crawls.admin.CrawlAdmin.should_annotate_snapshot_counts

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.should_annotate_snapshot_counts
```

````

````{py:method} hydrate_visible_snapshot_counts(crawls)
:canonical: archivebox.crawls.admin.CrawlAdmin.hydrate_visible_snapshot_counts

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.hydrate_visible_snapshot_counts
```

````

````{py:method} get_queryset(request)
:canonical: archivebox.crawls.admin.CrawlAdmin.get_queryset

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.get_queryset
```

````

````{py:method} change_view(request, object_id, form_url='', extra_context=None)
:canonical: archivebox.crawls.admin.CrawlAdmin.change_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.change_view
```

````

````{py:method} add_view(request, form_url='', extra_context=None)
:canonical: archivebox.crawls.admin.CrawlAdmin.add_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.add_view
```

````

````{py:method} get_fieldsets(request, obj=None)
:canonical: archivebox.crawls.admin.CrawlAdmin.get_fieldsets

````

````{py:method} get_urls()
:canonical: archivebox.crawls.admin.CrawlAdmin.get_urls

````

````{py:method} get_actions(request)
:canonical: archivebox.crawls.admin.CrawlAdmin.get_actions

````

````{py:method} delete_selected_batched(request, queryset)
:canonical: archivebox.crawls.admin.CrawlAdmin.delete_selected_batched

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.delete_selected_batched
```

````

````{py:method} pause_selected_crawls(request, queryset)
:canonical: archivebox.crawls.admin.CrawlAdmin.pause_selected_crawls

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.pause_selected_crawls
```

````

````{py:method} resume_selected_crawls(request, queryset)
:canonical: archivebox.crawls.admin.CrawlAdmin.resume_selected_crawls

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.resume_selected_crawls
```

````

````{py:method} seal_selected_crawls(request, queryset)
:canonical: archivebox.crawls.admin.CrawlAdmin.seal_selected_crawls

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.seal_selected_crawls
```

````

````{py:method} set_crawl_permissions(request, queryset)
:canonical: archivebox.crawls.admin.CrawlAdmin.set_crawl_permissions

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.set_crawl_permissions
```

````

````{py:method} update_crawl_permissions(queryset, permissions)
:canonical: archivebox.crawls.admin.CrawlAdmin.update_crawl_permissions

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.update_crawl_permissions
```

````

````{py:method} recrawl(request, obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.recrawl

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.recrawl
```

````

````{py:method} stop_reason_display(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.stop_reason_display

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.stop_reason_display
```

````

````{py:method} stop_reason_for_crawl(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.stop_reason_for_crawl

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.stop_reason_for_crawl
```

````

````{py:method} limit_config_for_crawl(obj, output_dir)
:canonical: archivebox.crawls.admin.CrawlAdmin.limit_config_for_crawl

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.limit_config_for_crawl
```

````

````{py:method} status_with_stop_reason(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.status_with_stop_reason

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.status_with_stop_reason
```

````

````{py:method} short_id(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.short_id

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.short_id
```

````

````{py:method} owner(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.owner

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.owner
```

````

````{py:method} depth(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.depth

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.depth
```

````

````{py:method} permissions_badge(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.permissions_badge

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.permissions_badge
```

````

````{py:method} pause_resume_control(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.pause_resume_control

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.pause_resume_control
```

````

````{py:method} num_archived_snapshots(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.num_archived_snapshots

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.num_archived_snapshots
```

````

````{py:method} num_total_snapshots(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.num_total_snapshots

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.num_total_snapshots
```

````

````{py:method} snapshots_changelist(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.snapshots_changelist

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.snapshots_changelist
```

````

````{py:method} delete_snapshot_view(request: django.http.HttpRequest, object_id: str, snapshot_id: str)
:canonical: archivebox.crawls.admin.CrawlAdmin.delete_snapshot_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.delete_snapshot_view
```

````

````{py:method} exclude_domain_view(request: django.http.HttpRequest, object_id: str, snapshot_id: str)
:canonical: archivebox.crawls.admin.CrawlAdmin.exclude_domain_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.exclude_domain_view
```

````

````{py:method} set_permissions_view(request: django.http.HttpRequest, object_id: str)
:canonical: archivebox.crawls.admin.CrawlAdmin.set_permissions_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.set_permissions_view
```

````

````{py:method} schedule_str(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.schedule_str

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.schedule_str
```

````

````{py:method} urls_preview(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.urls_preview

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.urls_preview
```

````

````{py:method} urls_editor(obj)
:canonical: archivebox.crawls.admin.CrawlAdmin.urls_editor

```{autodoc2-docstring} archivebox.crawls.admin.CrawlAdmin.urls_editor
```

````

``````

`````{py:class} CrawlScheduleAdmin(model, admin_site)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.list_display
:value: >
   ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str', 'crawls', 'num_crawls', 'num_sn...

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.sort_fields
:value: >
   ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str')

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.sort_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.search_fields
:value: >
   ('id', 'created_by__username', 'label', 'notes', 'schedule_id', 'template_id', 'template__urls')

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.readonly_fields
:value: >
   ('created_at', 'modified_at', 'crawls', 'snapshots')

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.fieldsets
:value: >
   (('Schedule Info',), ('Configuration',), ('Metadata',), ('Crawls',), ('Snapshots',))

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.list_filter
:value: >
   ('created_by',)

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.list_per_page
```

````

````{py:attribute} actions
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.actions
```

````

````{py:method} get_queryset(request)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.get_queryset

````

````{py:method} change_view(request, object_id, form_url='', extra_context=None)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.change_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.change_view
```

````

````{py:method} add_view(request, form_url='', extra_context=None)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.add_view

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.add_view
```

````

````{py:method} get_fieldsets(request, obj=None)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.get_fieldsets

````

````{py:method} save_model(request, obj, form, change)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.save_model

````

````{py:method} template_str(obj)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.template_str

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.template_str
```

````

````{py:method} num_crawls(obj)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.num_crawls

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.num_crawls
```

````

````{py:method} num_snapshots(obj)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.num_snapshots

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.num_snapshots
```

````

````{py:method} crawls(obj)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.crawls

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.crawls
```

````

````{py:method} snapshots(obj)
:canonical: archivebox.crawls.admin.CrawlScheduleAdmin.snapshots

```{autodoc2-docstring} archivebox.crawls.admin.CrawlScheduleAdmin.snapshots
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.crawls.admin.register_admin

```{autodoc2-docstring} archivebox.crawls.admin.register_admin
```
````
