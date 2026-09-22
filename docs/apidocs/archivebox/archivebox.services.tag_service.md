# {py:mod}`archivebox.services.tag_service`

```{py:module} archivebox.services.tag_service
```

```{autodoc2-docstring} archivebox.services.tag_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TagService <archivebox.services.tag_service.TagService>`
  -
````

### API

`````{py:class} TagService(bus)
:canonical: archivebox.services.tag_service.TagService

Bases: {py:obj}`abx_dl.services.base.BaseService`

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.tag_service.TagService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.tag_service.TagService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.tag_service.TagService.EMITS
:value: >
   []

```{autodoc2-docstring} archivebox.services.tag_service.TagService.EMITS
```

````

````{py:method} on_TagEvent__save_to_db(event: abx_dl.events.TagEvent) -> None
:canonical: archivebox.services.tag_service.TagService.on_TagEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.tag_service.TagService.on_TagEvent__save_to_db
```

````

`````
