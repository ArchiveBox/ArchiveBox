# {py:mod}`archivebox.services.crawl_service`

```{py:module} archivebox.services.crawl_service
```

```{autodoc2-docstring} archivebox.services.crawl_service
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CrawlService <archivebox.services.crawl_service.CrawlService>`
  -
````

### API

`````{py:class} CrawlService(bus, *, crawl_id: str)
:canonical: archivebox.services.crawl_service.CrawlService

Bases: {py:obj}`abx_dl.services.base.BaseService`

````{py:attribute} LISTENS_TO
:canonical: archivebox.services.crawl_service.CrawlService.LISTENS_TO
:value: >
   None

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.LISTENS_TO
```

````

````{py:attribute} EMITS
:canonical: archivebox.services.crawl_service.CrawlService.EMITS
:value: >
   []

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.EMITS
```

````

````{py:method} on_CrawlSetupEvent__save_to_db(event: abx_dl.events.CrawlSetupEvent) -> None
:canonical: archivebox.services.crawl_service.CrawlService.on_CrawlSetupEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.on_CrawlSetupEvent__save_to_db
```

````

````{py:method} on_CrawlStartEvent__save_to_db(event: abx_dl.events.CrawlStartEvent) -> None
:canonical: archivebox.services.crawl_service.CrawlService.on_CrawlStartEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.on_CrawlStartEvent__save_to_db
```

````

````{py:method} on_CrawlCleanupEvent__save_to_db(event: abx_dl.events.CrawlCleanupEvent) -> None
:canonical: archivebox.services.crawl_service.CrawlService.on_CrawlCleanupEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.on_CrawlCleanupEvent__save_to_db
```

````

````{py:method} on_CrawlCompletedEvent__save_to_db(event: abx_dl.events.CrawlCompletedEvent) -> None
:canonical: archivebox.services.crawl_service.CrawlService.on_CrawlCompletedEvent__save_to_db
:async:

```{autodoc2-docstring} archivebox.services.crawl_service.CrawlService.on_CrawlCompletedEvent__save_to_db
```

````

`````
