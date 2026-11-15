# {py:mod}`archivebox.config.forms`

```{py:module} archivebox.config.forms
```

```{autodoc2-docstring} archivebox.config.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineSettingsForm <archivebox.config.forms.MachineSettingsForm>`
  - ```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm
    :summary:
    ```
````

### API

`````{py:class} MachineSettingsForm(*args, machine, **kwargs)
:canonical: archivebox.config.forms.MachineSettingsForm

Bases: {py:obj}`archivebox.plugins.forms.PluginConfigFormMixin`, {py:obj}`django.forms.Form`

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.__init__
```

````{py:attribute} include_core_settings
:canonical: archivebox.config.forms.MachineSettingsForm.include_core_settings
:value: >
   True

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.include_core_settings
```

````

````{py:attribute} system_settings
:canonical: archivebox.config.forms.MachineSettingsForm.system_settings
:value: >
   True

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.system_settings
```

````

````{py:attribute} plugin_group_specs
:canonical: archivebox.config.forms.MachineSettingsForm.plugin_group_specs
:value: >
   ()

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.plugin_group_specs
```

````

````{py:attribute} config
:canonical: archivebox.config.forms.MachineSettingsForm.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.config
```

````

````{py:method} resolve_settings(config)
:canonical: archivebox.config.forms.MachineSettingsForm.resolve_settings

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.resolve_settings
```

````

````{py:method} clean()
:canonical: archivebox.config.forms.MachineSettingsForm.clean

```{autodoc2-docstring} archivebox.config.forms.MachineSettingsForm.clean
```

````

`````
