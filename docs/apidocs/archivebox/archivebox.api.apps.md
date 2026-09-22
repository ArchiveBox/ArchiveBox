# {py:mod}`archivebox.api.apps`

```{py:module} archivebox.api.apps
```

```{autodoc2-docstring} archivebox.api.apps
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`APIConfig <archivebox.api.apps.APIConfig>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin <archivebox.api.apps.register_admin>`
  - ```{autodoc2-docstring} archivebox.api.apps.register_admin
    :summary:
    ```
````

### API

`````{py:class} APIConfig(app_name, app_module)
:canonical: archivebox.api.apps.APIConfig

Bases: {py:obj}`django.apps.AppConfig`

````{py:attribute} name
:canonical: archivebox.api.apps.APIConfig.name
:value: >
   'archivebox.api'

```{autodoc2-docstring} archivebox.api.apps.APIConfig.name
```

````

````{py:attribute} label
:canonical: archivebox.api.apps.APIConfig.label
:value: >
   'api'

```{autodoc2-docstring} archivebox.api.apps.APIConfig.label
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.api.apps.register_admin

```{autodoc2-docstring} archivebox.api.apps.register_admin
```
````
