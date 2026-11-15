# {py:mod}`archivebox.core.asgi`

```{py:module} archivebox.core.asgi
```

```{autodoc2-docstring} archivebox.core.asgi
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveBoxASGIHandler <archivebox.core.asgi.ArchiveBoxASGIHandler>`
  - ```{autodoc2-docstring} archivebox.core.asgi.ArchiveBoxASGIHandler
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`application <archivebox.core.asgi.application>`
  - ```{autodoc2-docstring} archivebox.core.asgi.application
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`django_application <archivebox.core.asgi.django_application>`
  - ```{autodoc2-docstring} archivebox.core.asgi.django_application
    :summary:
    ```
````

### API

`````{py:class} ArchiveBoxASGIHandler
:canonical: archivebox.core.asgi.ArchiveBoxASGIHandler

Bases: {py:obj}`django.core.handlers.asgi.ASGIHandler`

```{autodoc2-docstring} archivebox.core.asgi.ArchiveBoxASGIHandler
```

````{py:method} create_request(scope, body_file)
:canonical: archivebox.core.asgi.ArchiveBoxASGIHandler.create_request

```{autodoc2-docstring} archivebox.core.asgi.ArchiveBoxASGIHandler.create_request
```

````

`````

````{py:data} django_application
:canonical: archivebox.core.asgi.django_application
:value: >
   'ArchiveBoxASGIHandler(...)'

```{autodoc2-docstring} archivebox.core.asgi.django_application
```

````

````{py:function} application(scope, receive, send)
:canonical: archivebox.core.asgi.application
:async:

```{autodoc2-docstring} archivebox.core.asgi.application
```
````
