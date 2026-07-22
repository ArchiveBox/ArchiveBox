# {py:mod}`archivebox.core.admin_site`

```{py:module} archivebox.core.admin_site
```

```{autodoc2-docstring} archivebox.core.admin_site
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveBoxLoginView <archivebox.core.admin_site.ArchiveBoxLoginView>`
  -
* - {py:obj}`ArchiveBoxAdmin <archivebox.core.admin_site.ArchiveBoxAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin_site <archivebox.core.admin_site.register_admin_site>`
  - ```{autodoc2-docstring} archivebox.core.admin_site.register_admin_site
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`archivebox_admin <archivebox.core.admin_site.archivebox_admin>`
  - ```{autodoc2-docstring} archivebox.core.admin_site.archivebox_admin
    :summary:
    ```
````

### API

`````{py:class} ArchiveBoxLoginView(**kwargs)
:canonical: archivebox.core.admin_site.ArchiveBoxLoginView

Bases: {py:obj}`django.contrib.auth.views.LoginView`

````{py:method} get_redirect_url() -> str
:canonical: archivebox.core.admin_site.ArchiveBoxLoginView.get_redirect_url

````

`````

`````{py:class} ArchiveBoxAdmin(name='admin')
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin

Bases: {py:obj}`django.contrib.admin.AdminSite`

````{py:attribute} site_header
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.site_header
:value: >
   'ArchiveBox'

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.site_header
```

````

````{py:attribute} index_title
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.index_title
:value: >
   'Admin Views'

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.index_title
```

````

````{py:attribute} site_title
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.site_title
:value: >
   'Admin'

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.site_title
```

````

````{py:attribute} namespace
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.namespace
:value: >
   'admin'

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.namespace
```

````

````{py:method} each_context(request: django.http.HttpRequest) -> dict[str, typing.Any]
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.each_context

````

````{py:method} _format_object_count(count: int) -> tuple[int, str, str]
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin._format_object_count
:staticmethod:

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin._format_object_count
```

````

````{py:method} _set_model_object_count(models_by_table: dict[str, list[dict[str, typing.Any]]], table: str, count: int, title: str | None = None) -> None
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin._set_model_object_count

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin._set_model_object_count
```

````

````{py:method} get_app_list(request: django.http.HttpRequest, app_label: str | None = None) -> list[admin_data_views.typing.AppDict]
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.get_app_list

````

````{py:method} admin_data_index_view(request: django.http.HttpRequest, **kwargs: typing.Any) -> django.template.response.TemplateResponse
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.admin_data_index_view

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.admin_data_index_view
```

````

````{py:method} login(request: django.http.HttpRequest, extra_context: dict[str, typing.Any] | None = None) -> django.template.response.TemplateResponse
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.login

````

````{py:method} index(request: django.http.HttpRequest, extra_context: dict[str, typing.Any] | None = None) -> django.template.response.TemplateResponse
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.index

````

````{py:method} get_admin_data_urls() -> list[URLResolver | URLPattern]
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.get_admin_data_urls

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.get_admin_data_urls
```

````

````{py:method} get_urls() -> list[URLResolver | URLPattern]
:canonical: archivebox.core.admin_site.ArchiveBoxAdmin.get_urls

```{autodoc2-docstring} archivebox.core.admin_site.ArchiveBoxAdmin.get_urls
```

````

`````

````{py:data} archivebox_admin
:canonical: archivebox.core.admin_site.archivebox_admin
:value: >
   'ArchiveBoxAdmin(...)'

```{autodoc2-docstring} archivebox.core.admin_site.archivebox_admin
```

````

````{py:function} register_admin_site()
:canonical: archivebox.core.admin_site.register_admin_site

```{autodoc2-docstring} archivebox.core.admin_site.register_admin_site
```
````
