# {py:mod}`archivebox.core.admin_folders`

```{py:module} archivebox.core.admin_folders
```

```{autodoc2-docstring} archivebox.core.admin_folders
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FolderForm <archivebox.core.admin_folders.FolderForm>`
  - ```{autodoc2-docstring} archivebox.core.admin_folders.FolderForm
    :summary:
    ```
* - {py:obj}`FolderAdmin <archivebox.core.admin_folders.FolderAdmin>`
  - ```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin
    :summary:
    ```
````

### API

``````{py:class} FolderForm
:canonical: archivebox.core.admin_folders.FolderForm

Bases: {py:obj}`django.forms.ModelForm`

```{autodoc2-docstring} archivebox.core.admin_folders.FolderForm
```

`````{py:class} Meta
:canonical: archivebox.core.admin_folders.FolderForm.Meta

```{autodoc2-docstring} archivebox.core.admin_folders.FolderForm.Meta
```

````{py:attribute} model
:canonical: archivebox.core.admin_folders.FolderForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_folders.FolderForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_folders.FolderForm.Meta.fields
:value: >
   ('name', 'parent', 'rules')

```{autodoc2-docstring} archivebox.core.admin_folders.FolderForm.Meta.fields
```

````

`````

``````

`````{py:class} FolderAdmin
:canonical: archivebox.core.admin_folders.FolderAdmin

Bases: {py:obj}`django.contrib.admin.ModelAdmin`

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin
```

````{py:attribute} change_list_template
:canonical: archivebox.core.admin_folders.FolderAdmin.change_list_template
:value: >
   'admin/core/folder/change_list.html'

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.change_list_template
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_folders.FolderAdmin.list_display
:value: >
   ('name', 'parent', 'position', 'created_by')

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.list_display
```

````

````{py:attribute} list_select_related
:canonical: archivebox.core.admin_folders.FolderAdmin.list_select_related
:value: >
   ('parent', 'created_by')

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.list_select_related
```

````

````{py:attribute} list_editable
:canonical: archivebox.core.admin_folders.FolderAdmin.list_editable
:value: >
   ('position',)

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.list_editable
```

````

````{py:attribute} search_fields
:canonical: archivebox.core.admin_folders.FolderAdmin.search_fields
:value: >
   ('name',)

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.search_fields
```

````

````{py:attribute} fields
:canonical: archivebox.core.admin_folders.FolderAdmin.fields
:value: >
   ('name', 'parent', 'rules', 'position', 'created_by')

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_folders.FolderAdmin.readonly_fields
:value: >
   ('created_by',)

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.readonly_fields
```

````

````{py:method} save_model(request, obj, form, change)
:canonical: archivebox.core.admin_folders.FolderAdmin.save_model

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.save_model
```

````

````{py:method} get_urls()
:canonical: archivebox.core.admin_folders.FolderAdmin.get_urls

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.get_urls
```

````

````{py:method} export_folders(request, format)
:canonical: archivebox.core.admin_folders.FolderAdmin.export_folders

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.export_folders
```

````

````{py:method} delete_folder(request)
:canonical: archivebox.core.admin_folders.FolderAdmin.delete_folder

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.delete_folder
```

````

````{py:method} get_deleted_objects(objs, request)
:canonical: archivebox.core.admin_folders.FolderAdmin.get_deleted_objects

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.get_deleted_objects
```

````

````{py:method} delete_queryset(request, queryset)
:canonical: archivebox.core.admin_folders.FolderAdmin.delete_queryset

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.delete_queryset
```

````

````{py:method} rule_schema(request)
:canonical: archivebox.core.admin_folders.FolderAdmin.rule_schema

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.rule_schema
```

````

````{py:method} move_folder(request)
:canonical: archivebox.core.admin_folders.FolderAdmin.move_folder

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.move_folder
```

````

````{py:method} save_folder(request)
:canonical: archivebox.core.admin_folders.FolderAdmin.save_folder

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.save_folder
```

````

````{py:method} formfield_for_foreignkey(db_field, request, **kwargs)
:canonical: archivebox.core.admin_folders.FolderAdmin.formfield_for_foreignkey

```{autodoc2-docstring} archivebox.core.admin_folders.FolderAdmin.formfield_for_foreignkey
```

````

`````
