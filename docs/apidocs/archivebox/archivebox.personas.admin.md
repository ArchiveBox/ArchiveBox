# {py:mod}`archivebox.personas.admin`

```{py:module} archivebox.personas.admin
```

```{autodoc2-docstring} archivebox.personas.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PersonaAdmin <archivebox.personas.admin.PersonaAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin <archivebox.personas.admin.register_admin>`
  - ```{autodoc2-docstring} archivebox.personas.admin.register_admin
    :summary:
    ```
````

### API

`````{py:class} PersonaAdmin(model, admin_site)
:canonical: archivebox.personas.admin.PersonaAdmin

Bases: {py:obj}`archivebox.base_models.admin.ConfigEditorMixin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} form
:canonical: archivebox.personas.admin.PersonaAdmin.form
:value: >
   None

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.form
```

````

````{py:attribute} change_form_template
:canonical: archivebox.personas.admin.PersonaAdmin.change_form_template
:value: >
   'admin/personas/persona/change_form.html'

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.change_form_template
```

````

````{py:attribute} list_display
:canonical: archivebox.personas.admin.PersonaAdmin.list_display
:value: >
   ('name', 'created_by', 'created_at', 'chrome_profile_state', 'cookies_state', 'auth_state')

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.list_display
```

````

````{py:attribute} search_fields
:canonical: archivebox.personas.admin.PersonaAdmin.search_fields
:value: >
   ('name', 'created_by__username')

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.search_fields
```

````

````{py:attribute} list_filter
:canonical: archivebox.personas.admin.PersonaAdmin.list_filter
:value: >
   ('created_by',)

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.personas.admin.PersonaAdmin.ordering
:value: >
   ['name']

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.personas.admin.PersonaAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.list_per_page
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.personas.admin.PersonaAdmin.readonly_fields
:value: >
   ('id', 'created_at', 'persona_paths', 'import_artifact_status')

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.readonly_fields
```

````

````{py:attribute} add_fieldsets
:canonical: archivebox.personas.admin.PersonaAdmin.add_fieldsets
:value: >
   (('Persona',), ('Browser Import',), ('Advanced',))

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.add_fieldsets
```

````

````{py:attribute} change_fieldsets
:canonical: archivebox.personas.admin.PersonaAdmin.change_fieldsets
:value: >
   ()

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.change_fieldsets
```

````

````{py:method} chrome_profile_state(obj: archivebox.personas.models.Persona) -> str
:canonical: archivebox.personas.admin.PersonaAdmin.chrome_profile_state

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.chrome_profile_state
```

````

````{py:method} cookies_state(obj: archivebox.personas.models.Persona) -> str
:canonical: archivebox.personas.admin.PersonaAdmin.cookies_state

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.cookies_state
```

````

````{py:method} auth_state(obj: archivebox.personas.models.Persona) -> str
:canonical: archivebox.personas.admin.PersonaAdmin.auth_state

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.auth_state
```

````

````{py:method} persona_paths(obj: archivebox.personas.models.Persona) -> str
:canonical: archivebox.personas.admin.PersonaAdmin.persona_paths

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.persona_paths
```

````

````{py:method} import_artifact_status(obj: archivebox.personas.models.Persona) -> str
:canonical: archivebox.personas.admin.PersonaAdmin.import_artifact_status

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.import_artifact_status
```

````

````{py:method} get_fieldsets(request, obj=None)
:canonical: archivebox.personas.admin.PersonaAdmin.get_fieldsets

````

````{py:method} get_form(request, obj=None, change=False, **kwargs)
:canonical: archivebox.personas.admin.PersonaAdmin.get_form

````

````{py:method} render_change_form(request, context, add=False, change=False, form_url='', obj=None)
:canonical: archivebox.personas.admin.PersonaAdmin.render_change_form

```{autodoc2-docstring} archivebox.personas.admin.PersonaAdmin.render_change_form
```

````

````{py:method} save_model(request, obj, form, change)
:canonical: archivebox.personas.admin.PersonaAdmin.save_model

````

`````

````{py:function} register_admin(admin_site: django.contrib.admin.AdminSite) -> None
:canonical: archivebox.personas.admin.register_admin

```{autodoc2-docstring} archivebox.personas.admin.register_admin
```
````
