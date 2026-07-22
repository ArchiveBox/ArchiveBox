# {py:mod}`archivebox.personas.forms`

```{py:module} archivebox.personas.forms
```

```{autodoc2-docstring} archivebox.personas.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PersonaAdminForm <archivebox.personas.forms.PersonaAdminForm>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_mode_label <archivebox.personas.forms._mode_label>`
  - ```{autodoc2-docstring} archivebox.personas.forms._mode_label
    :summary:
    ```
````

### API

````{py:function} _mode_label(title: str, description: str) -> str
:canonical: archivebox.personas.forms._mode_label

```{autodoc2-docstring} archivebox.personas.forms._mode_label
```
````

``````{py:class} PersonaAdminForm(*args: typing.Any, **kwargs: typing.Any)
:canonical: archivebox.personas.forms.PersonaAdminForm

Bases: {py:obj}`archivebox.plugins.forms.PluginConfigFormMixin`, {py:obj}`django.forms.ModelForm`

````{py:attribute} permissions
:canonical: archivebox.personas.forms.PersonaAdminForm.permissions
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.permissions
```

````

````{py:attribute} import_mode
:canonical: archivebox.personas.forms.PersonaAdminForm.import_mode
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_mode
```

````

````{py:attribute} import_discovered_profile
:canonical: archivebox.personas.forms.PersonaAdminForm.import_discovered_profile
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_discovered_profile
```

````

````{py:attribute} import_source
:canonical: archivebox.personas.forms.PersonaAdminForm.import_source
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_source
```

````

````{py:attribute} import_profile_name
:canonical: archivebox.personas.forms.PersonaAdminForm.import_profile_name
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_profile_name
```

````

````{py:attribute} import_copy_profile
:canonical: archivebox.personas.forms.PersonaAdminForm.import_copy_profile
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_copy_profile
```

````

````{py:attribute} import_extract_cookies
:canonical: archivebox.personas.forms.PersonaAdminForm.import_extract_cookies
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_extract_cookies
```

````

````{py:attribute} import_capture_storage
:canonical: archivebox.personas.forms.PersonaAdminForm.import_capture_storage
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.import_capture_storage
```

````

`````{py:class} Meta
:canonical: archivebox.personas.forms.PersonaAdminForm.Meta

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.Meta
```

````{py:attribute} model
:canonical: archivebox.personas.forms.PersonaAdminForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.personas.forms.PersonaAdminForm.Meta.fields
:value: >
   ('name', 'created_by', 'config')

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.Meta.fields
```

````

`````

````{py:method} clean_name() -> str
:canonical: archivebox.personas.forms.PersonaAdminForm.clean_name

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.clean_name
```

````

````{py:method} clean() -> dict[str, typing.Any]
:canonical: archivebox.personas.forms.PersonaAdminForm.clean

````

````{py:method} apply_import(persona: archivebox.personas.models.Persona) -> archivebox.personas.importers.PersonaImportResult | None
:canonical: archivebox.personas.forms.PersonaAdminForm.apply_import

```{autodoc2-docstring} archivebox.personas.forms.PersonaAdminForm.apply_import
```

````

``````
