# {py:mod}`archivebox.machine.apps`

```{py:module} archivebox.machine.apps
```

```{autodoc2-docstring} archivebox.machine.apps
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MachineConfig <archivebox.machine.apps.MachineConfig>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin <archivebox.machine.apps.register_admin>`
  - ```{autodoc2-docstring} archivebox.machine.apps.register_admin
    :summary:
    ```
````

### API

`````{py:class} MachineConfig(app_name, app_module)
:canonical: archivebox.machine.apps.MachineConfig

Bases: {py:obj}`django.apps.AppConfig`

````{py:attribute} default_auto_field
:canonical: archivebox.machine.apps.MachineConfig.default_auto_field
:value: >
   'django.db.models.BigAutoField'

```{autodoc2-docstring} archivebox.machine.apps.MachineConfig.default_auto_field
```

````

````{py:attribute} name
:canonical: archivebox.machine.apps.MachineConfig.name
:value: >
   'archivebox.machine'

```{autodoc2-docstring} archivebox.machine.apps.MachineConfig.name
```

````

````{py:attribute} label
:canonical: archivebox.machine.apps.MachineConfig.label
:value: >
   'machine'

```{autodoc2-docstring} archivebox.machine.apps.MachineConfig.label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.machine.apps.MachineConfig.verbose_name
:value: >
   'Machine Info'

```{autodoc2-docstring} archivebox.machine.apps.MachineConfig.verbose_name
```

````

````{py:method} ready()
:canonical: archivebox.machine.apps.MachineConfig.ready

```{autodoc2-docstring} archivebox.machine.apps.MachineConfig.ready
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.machine.apps.register_admin

```{autodoc2-docstring} archivebox.machine.apps.register_admin
```
````
