# {py:mod}`archivebox.search.query`

```{py:module} archivebox.search.query
```

```{autodoc2-docstring} archivebox.search.query
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`escape_like_query <archivebox.search.query.escape_like_query>`
  - ```{autodoc2-docstring} archivebox.search.query.escape_like_query
    :summary:
    ```
* - {py:obj}`crawl_config_values_search_wave <archivebox.search.query.crawl_config_values_search_wave>`
  - ```{autodoc2-docstring} archivebox.search.query.crawl_config_values_search_wave
    :summary:
    ```
* - {py:obj}`snapshot_metadata_search_waves <archivebox.search.query.snapshot_metadata_search_waves>`
  - ```{autodoc2-docstring} archivebox.search.query.snapshot_metadata_search_waves
    :summary:
    ```
* - {py:obj}`prioritize_metadata_matches <archivebox.search.query.prioritize_metadata_matches>`
  - ```{autodoc2-docstring} archivebox.search.query.prioritize_metadata_matches
    :summary:
    ```
* - {py:obj}`apply_snapshot_search <archivebox.search.query.apply_snapshot_search>`
  - ```{autodoc2-docstring} archivebox.search.query.apply_snapshot_search
    :summary:
    ```
* - {py:obj}`query_search_index <archivebox.search.query.query_search_index>`
  - ```{autodoc2-docstring} archivebox.search.query.query_search_index
    :summary:
    ```
* - {py:obj}`iter_query_search_ids <archivebox.search.query.iter_query_search_ids>`
  - ```{autodoc2-docstring} archivebox.search.query.iter_query_search_ids
    :summary:
    ```
* - {py:obj}`flush_search_index <archivebox.search.query.flush_search_index>`
  - ```{autodoc2-docstring} archivebox.search.query.flush_search_index
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MAX_SEARCH_RANK_IDS <archivebox.search.query.MAX_SEARCH_RANK_IDS>`
  - ```{autodoc2-docstring} archivebox.search.query.MAX_SEARCH_RANK_IDS
    :summary:
    ```
````

### API

````{py:data} MAX_SEARCH_RANK_IDS
:canonical: archivebox.search.query.MAX_SEARCH_RANK_IDS
:value: >
   500

```{autodoc2-docstring} archivebox.search.query.MAX_SEARCH_RANK_IDS
```

````

````{py:function} escape_like_query(query: str) -> str
:canonical: archivebox.search.query.escape_like_query

```{autodoc2-docstring} archivebox.search.query.escape_like_query
```
````

````{py:function} crawl_config_values_search_wave(query: str) -> django.db.models.Q | None
:canonical: archivebox.search.query.crawl_config_values_search_wave

```{autodoc2-docstring} archivebox.search.query.crawl_config_values_search_wave
```
````

````{py:function} snapshot_metadata_search_waves(query: str, *, include_id_matches: bool = False) -> list[django.db.models.Q]
:canonical: archivebox.search.query.snapshot_metadata_search_waves

```{autodoc2-docstring} archivebox.search.query.snapshot_metadata_search_waves
```
````

````{py:function} prioritize_metadata_matches(base_queryset: django.db.models.QuerySet, metadata_queryset: django.db.models.QuerySet, fulltext_queryset: django.db.models.QuerySet, *, deep_queryset: django.db.models.QuerySet | None = None, ordering: list[str] | tuple[str, ...] | None = None) -> django.db.models.QuerySet
:canonical: archivebox.search.query.prioritize_metadata_matches

```{autodoc2-docstring} archivebox.search.query.prioritize_metadata_matches
```
````

````{py:function} apply_snapshot_search(base_queryset: django.db.models.QuerySet, query: str, *, search_mode: str | None = None, config: dict[str, typing.Any] | None = None, ordering: list[str] | tuple[str, ...] | None = None, max_results: int | None = None, skip_backend_when_metadata_satisfies_limit: bool = False, include_metadata_for_forced_backend: bool = False, include_id_matches: bool = False) -> django.db.models.QuerySet
:canonical: archivebox.search.query.apply_snapshot_search

```{autodoc2-docstring} archivebox.search.query.apply_snapshot_search
```
````

````{py:function} query_search_index(query: str, search_mode: str | None = None, config: dict[str, typing.Any] | None = None, max_results: int | None = None, **config_kwargs: typing.Any) -> django.db.models.QuerySet
:canonical: archivebox.search.query.query_search_index

```{autodoc2-docstring} archivebox.search.query.query_search_index
```
````

````{py:function} iter_query_search_ids(query: str, search_mode: str | None = None, config: dict[str, typing.Any] | None = None, max_results: int | None = None, **config_kwargs: typing.Any)
:canonical: archivebox.search.query.iter_query_search_ids

```{autodoc2-docstring} archivebox.search.query.iter_query_search_ids
```
````

````{py:function} flush_search_index(snapshots: django.db.models.QuerySet, config: dict[str, typing.Any] | None = None, **config_kwargs: typing.Any) -> None
:canonical: archivebox.search.query.flush_search_index

```{autodoc2-docstring} archivebox.search.query.flush_search_index
```
````
