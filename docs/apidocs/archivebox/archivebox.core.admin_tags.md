# {py:mod}`archivebox.core.admin_tags`

```{py:module} archivebox.core.admin_tags
```

```{autodoc2-docstring} archivebox.core.admin_tags
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TagInline <archivebox.core.admin_tags.TagInline>`
  -
* - {py:obj}`TagAdminForm <archivebox.core.admin_tags.TagAdminForm>`
  -
* - {py:obj}`TagAdmin <archivebox.core.admin_tags.TagAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin <archivebox.core.admin_tags.register_admin>`
  - ```{autodoc2-docstring} archivebox.core.admin_tags.register_admin
    :summary:
    ```
````

### API

`````{py:class} TagInline(parent_model, admin_site)
:canonical: archivebox.core.admin_tags.TagInline

Bases: {py:obj}`django.contrib.admin.TabularInline`

````{py:attribute} model
:canonical: archivebox.core.admin_tags.TagInline.model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_tags.TagInline.model
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_tags.TagInline.fields
:value: >
   ('id', 'tag')

```{autodoc2-docstring} archivebox.core.admin_tags.TagInline.fields
```

````

````{py:attribute} extra
:canonical: archivebox.core.admin_tags.TagInline.extra
:value: >
   1

```{autodoc2-docstring} archivebox.core.admin_tags.TagInline.extra
```

````

````{py:attribute} max_num
:canonical: archivebox.core.admin_tags.TagInline.max_num
:value: >
   1000

```{autodoc2-docstring} archivebox.core.admin_tags.TagInline.max_num
```

````

````{py:attribute} autocomplete_fields
:canonical: archivebox.core.admin_tags.TagInline.autocomplete_fields
:value: >
   ('tag',)

```{autodoc2-docstring} archivebox.core.admin_tags.TagInline.autocomplete_fields
```

````

`````

``````{py:class} TagAdminForm(data=None, files=None, auto_id='id_%s', prefix=None, initial=None, error_class=ErrorList, label_suffix=None, empty_permitted=False, instance=None, use_required_attribute=None, renderer=None)
:canonical: archivebox.core.admin_tags.TagAdminForm

Bases: {py:obj}`django.forms.ModelForm`

`````{py:class} Meta
:canonical: archivebox.core.admin_tags.TagAdminForm.Meta

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdminForm.Meta
```

````{py:attribute} model
:canonical: archivebox.core.admin_tags.TagAdminForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdminForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_tags.TagAdminForm.Meta.fields
:value: >
   '__all__'

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdminForm.Meta.fields
```

````

````{py:attribute} widgets
:canonical: archivebox.core.admin_tags.TagAdminForm.Meta.widgets
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdminForm.Meta.widgets
```

````

`````

````{py:method} clean_name()
:canonical: archivebox.core.admin_tags.TagAdminForm.clean_name

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdminForm.clean_name
```

````

``````

`````{py:class} TagAdmin(model, admin_site)
:canonical: archivebox.core.admin_tags.TagAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} form
:canonical: archivebox.core.admin_tags.TagAdmin.form
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.form
```

````

````{py:attribute} change_list_template
:canonical: archivebox.core.admin_tags.TagAdmin.change_list_template
:value: >
   'admin/core/tag/change_list.html'

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.change_list_template
```

````

````{py:attribute} change_form_template
:canonical: archivebox.core.admin_tags.TagAdmin.change_form_template
:value: >
   'admin/core/tag/change_form.html'

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.change_form_template
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_tags.TagAdmin.list_display
:value: >
   ('name', 'num_snapshots', 'created_at', 'created_by')

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.list_display
```

````

````{py:attribute} list_filter
:canonical: archivebox.core.admin_tags.TagAdmin.list_filter
:value: >
   ('created_at', 'created_by')

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.list_filter
```

````

````{py:attribute} search_fields
:canonical: archivebox.core.admin_tags.TagAdmin.search_fields
:value: >
   ('id', 'name')

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.search_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_tags.TagAdmin.readonly_fields
:value: >
   ('id', 'created_at', 'modified_at', 'snapshots')

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.readonly_fields
```

````

````{py:attribute} actions
:canonical: archivebox.core.admin_tags.TagAdmin.actions
:value: >
   ['delete_selected']

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.actions
```

````

````{py:attribute} ordering
:canonical: archivebox.core.admin_tags.TagAdmin.ordering
:value: >
   ['name', 'id']

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.ordering
```

````

````{py:attribute} fieldsets
:canonical: archivebox.core.admin_tags.TagAdmin.fieldsets
:value: >
   (('Tag',), ('Metadata',), ('Recent Snapshots',))

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.fieldsets
```

````

````{py:attribute} add_fieldsets
:canonical: archivebox.core.admin_tags.TagAdmin.add_fieldsets
:value: >
   (('Tag',), ('Metadata',))

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.add_fieldsets
```

````

````{py:method} get_fieldsets(request: django.http.HttpRequest, obj: archivebox.core.models.Tag | None = None)
:canonical: archivebox.core.admin_tags.TagAdmin.get_fieldsets

````

````{py:method} changelist_view(request: django.http.HttpRequest, extra_context=None)
:canonical: archivebox.core.admin_tags.TagAdmin.changelist_view

````

````{py:method} render_change_form(request, context, add=False, change=False, form_url='', obj=None)
:canonical: archivebox.core.admin_tags.TagAdmin.render_change_form

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.render_change_form
```

````

````{py:method} response_add(request: django.http.HttpRequest, obj: archivebox.core.models.Tag, post_url_continue=None)
:canonical: archivebox.core.admin_tags.TagAdmin.response_add

````

````{py:method} response_change(request: django.http.HttpRequest, obj: archivebox.core.models.Tag)
:canonical: archivebox.core.admin_tags.TagAdmin.response_change

````

````{py:method} _redirect_to_changelist(query: str = '') -> django.http.HttpResponseRedirect
:canonical: archivebox.core.admin_tags.TagAdmin._redirect_to_changelist

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin._redirect_to_changelist
```

````

````{py:method} snapshots(tag: archivebox.core.models.Tag)
:canonical: archivebox.core.admin_tags.TagAdmin.snapshots

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.snapshots
```

````

````{py:method} num_snapshots(tag: archivebox.core.models.Tag)
:canonical: archivebox.core.admin_tags.TagAdmin.num_snapshots

```{autodoc2-docstring} archivebox.core.admin_tags.TagAdmin.num_snapshots
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.core.admin_tags.register_admin

```{autodoc2-docstring} archivebox.core.admin_tags.register_admin
```
````
