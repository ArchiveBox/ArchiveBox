# {py:mod}`archivebox.importers.forms`

```{py:module} archivebox.importers.forms
```

```{autodoc2-docstring} archivebox.importers.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ImporterSourceForm <archivebox.importers.forms.ImporterSourceForm>`
  - ```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm
    :summary:
    ```
````

### API

``````{py:class} ImporterSourceForm(*args, definition, **kwargs)
:canonical: archivebox.importers.forms.ImporterSourceForm

Bases: {py:obj}`django.forms.ModelForm`

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.__init__
```

`````{py:class} Meta
:canonical: archivebox.importers.forms.ImporterSourceForm.Meta

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.Meta
```

````{py:attribute} model
:canonical: archivebox.importers.forms.ImporterSourceForm.Meta.model
:value: >
   None

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.Meta.model
```

````

````{py:attribute} fields
:canonical: archivebox.importers.forms.ImporterSourceForm.Meta.fields
:value: >
   ('name', 'persona', 'folder', 'limit', 'tags', 'schedule')

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.Meta.fields
```

````

````{py:attribute} help_texts
:canonical: archivebox.importers.forms.ImporterSourceForm.Meta.help_texts
:type: typing.ClassVar
:value: >
   None

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.Meta.help_texts
```

````

`````

````{py:property} basic_fields
:canonical: archivebox.importers.forms.ImporterSourceForm.basic_fields

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.basic_fields
```

````

````{py:property} advanced_names
:canonical: archivebox.importers.forms.ImporterSourceForm.advanced_names

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.advanced_names
```

````

````{py:property} advanced_fields
:canonical: archivebox.importers.forms.ImporterSourceForm.advanced_fields

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.advanced_fields
```

````

````{py:property} advanced_errors
:canonical: archivebox.importers.forms.ImporterSourceForm.advanced_errors

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.advanced_errors
```

````

````{py:method} clean_folder()
:canonical: archivebox.importers.forms.ImporterSourceForm.clean_folder

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.clean_folder
```

````

````{py:method} clean_name()
:canonical: archivebox.importers.forms.ImporterSourceForm.clean_name

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.clean_name
```

````

````{py:method} clean_limit()
:canonical: archivebox.importers.forms.ImporterSourceForm.clean_limit

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.clean_limit
```

````

````{py:method} clean_schedule()
:canonical: archivebox.importers.forms.ImporterSourceForm.clean_schedule

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.clean_schedule
```

````

````{py:method} clean()
:canonical: archivebox.importers.forms.ImporterSourceForm.clean

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.clean
```

````

````{py:method} save(commit=True, *, enabled=None)
:canonical: archivebox.importers.forms.ImporterSourceForm.save

```{autodoc2-docstring} archivebox.importers.forms.ImporterSourceForm.save
```

````

``````
