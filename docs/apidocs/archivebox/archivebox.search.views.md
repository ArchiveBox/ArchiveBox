# {py:mod}`archivebox.search.views`

```{py:module} archivebox.search.views
```

```{autodoc2-docstring} archivebox.search.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_admin_search_cache_key <archivebox.search.views.get_admin_search_cache_key>`
  - ```{autodoc2-docstring} archivebox.search.views.get_admin_search_cache_key
    :summary:
    ```
* - {py:obj}`get_public_search_cache_key <archivebox.search.views.get_public_search_cache_key>`
  - ```{autodoc2-docstring} archivebox.search.views.get_public_search_cache_key
    :summary:
    ```
* - {py:obj}`get_cached_admin_search_ids <archivebox.search.views.get_cached_admin_search_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.get_cached_admin_search_ids
    :summary:
    ```
* - {py:obj}`get_cached_public_search_ids <archivebox.search.views.get_cached_public_search_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.get_cached_public_search_ids
    :summary:
    ```
* - {py:obj}`get_cached_public_search_state <archivebox.search.views.get_cached_public_search_state>`
  - ```{autodoc2-docstring} archivebox.search.views.get_cached_public_search_state
    :summary:
    ```
* - {py:obj}`iter_url_search_prefixes <archivebox.search.views.iter_url_search_prefixes>`
  - ```{autodoc2-docstring} archivebox.search.views.iter_url_search_prefixes
    :summary:
    ```
* - {py:obj}`url_prefix_upper_bound <archivebox.search.views.url_prefix_upper_bound>`
  - ```{autodoc2-docstring} archivebox.search.views.url_prefix_upper_bound
    :summary:
    ```
* - {py:obj}`iter_url_prefix_search_ids <archivebox.search.views.iter_url_prefix_search_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.iter_url_prefix_search_ids
    :summary:
    ```
* - {py:obj}`iter_meta_search_ids <archivebox.search.views.iter_meta_search_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.iter_meta_search_ids
    :summary:
    ```
* - {py:obj}`normalize_search_result_id <archivebox.search.views.normalize_search_result_id>`
  - ```{autodoc2-docstring} archivebox.search.views.normalize_search_result_id
    :summary:
    ```
* - {py:obj}`iter_filtered_search_result_ids <archivebox.search.views.iter_filtered_search_result_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.iter_filtered_search_result_ids
    :summary:
    ```
* - {py:obj}`iter_search_result_ids <archivebox.search.views.iter_search_result_ids>`
  - ```{autodoc2-docstring} archivebox.search.views.iter_search_result_ids
    :summary:
    ```
* - {py:obj}`snapshot_search_stream_response <archivebox.search.views.snapshot_search_stream_response>`
  - ```{autodoc2-docstring} archivebox.search.views.snapshot_search_stream_response
    :summary:
    ```
* - {py:obj}`admin_snapshot_search_stream_view <archivebox.search.views.admin_snapshot_search_stream_view>`
  - ```{autodoc2-docstring} archivebox.search.views.admin_snapshot_search_stream_view
    :summary:
    ```
* - {py:obj}`public_snapshot_search_stream_view <archivebox.search.views.public_snapshot_search_stream_view>`
  - ```{autodoc2-docstring} archivebox.search.views.public_snapshot_search_stream_view
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SEARCH_RESULT_CACHE_TTL <archivebox.search.views.SEARCH_RESULT_CACHE_TTL>`
  - ```{autodoc2-docstring} archivebox.search.views.SEARCH_RESULT_CACHE_TTL
    :summary:
    ```
* - {py:obj}`URL_PREFIX_SEARCH_LIMIT <archivebox.search.views.URL_PREFIX_SEARCH_LIMIT>`
  - ```{autodoc2-docstring} archivebox.search.views.URL_PREFIX_SEARCH_LIMIT
    :summary:
    ```
````

### API

````{py:data} SEARCH_RESULT_CACHE_TTL
:canonical: archivebox.search.views.SEARCH_RESULT_CACHE_TTL
:value: >
   60

```{autodoc2-docstring} archivebox.search.views.SEARCH_RESULT_CACHE_TTL
```

````

````{py:data} URL_PREFIX_SEARCH_LIMIT
:canonical: archivebox.search.views.URL_PREFIX_SEARCH_LIMIT
:value: >
   500

```{autodoc2-docstring} archivebox.search.views.URL_PREFIX_SEARCH_LIMIT
```

````

````{py:function} get_admin_search_cache_key(request, url: str | None = None) -> str
:canonical: archivebox.search.views.get_admin_search_cache_key

```{autodoc2-docstring} archivebox.search.views.get_admin_search_cache_key
```
````

````{py:function} get_public_search_cache_key(request, url: str | None = None) -> str
:canonical: archivebox.search.views.get_public_search_cache_key

```{autodoc2-docstring} archivebox.search.views.get_public_search_cache_key
```
````

````{py:function} get_cached_admin_search_ids(request) -> list[str] | None
:canonical: archivebox.search.views.get_cached_admin_search_ids

```{autodoc2-docstring} archivebox.search.views.get_cached_admin_search_ids
```
````

````{py:function} get_cached_public_search_ids(request) -> list[str] | None
:canonical: archivebox.search.views.get_cached_public_search_ids

```{autodoc2-docstring} archivebox.search.views.get_cached_public_search_ids
```
````

````{py:function} get_cached_public_search_state(request) -> dict | None
:canonical: archivebox.search.views.get_cached_public_search_state

```{autodoc2-docstring} archivebox.search.views.get_cached_public_search_state
```
````

````{py:function} iter_url_search_prefixes(query: str)
:canonical: archivebox.search.views.iter_url_search_prefixes

```{autodoc2-docstring} archivebox.search.views.iter_url_search_prefixes
```
````

````{py:function} url_prefix_upper_bound(prefix: str) -> str
:canonical: archivebox.search.views.url_prefix_upper_bound

```{autodoc2-docstring} archivebox.search.views.url_prefix_upper_bound
```
````

````{py:function} iter_url_prefix_search_ids(prefix: str, queryset)
:canonical: archivebox.search.views.iter_url_prefix_search_ids

```{autodoc2-docstring} archivebox.search.views.iter_url_prefix_search_ids
```
````

````{py:function} iter_meta_search_ids(query, queryset)
:canonical: archivebox.search.views.iter_meta_search_ids

```{autodoc2-docstring} archivebox.search.views.iter_meta_search_ids
```
````

````{py:function} normalize_search_result_id(snapshot_id) -> str | None
:canonical: archivebox.search.views.normalize_search_result_id

```{autodoc2-docstring} archivebox.search.views.normalize_search_result_id
```
````

````{py:function} iter_filtered_search_result_ids(iterator, queryset, *, flush_max_delay=0.05)
:canonical: archivebox.search.views.iter_filtered_search_result_ids

```{autodoc2-docstring} archivebox.search.views.iter_filtered_search_result_ids
```
````

````{py:function} iter_search_result_ids(query, base_queryset, *, search_mode, config)
:canonical: archivebox.search.views.iter_search_result_ids

```{autodoc2-docstring} archivebox.search.views.iter_search_result_ids
```
````

````{py:function} snapshot_search_stream_response(query, base_queryset, *, search_mode, config, cache_key, thread_name)
:canonical: archivebox.search.views.snapshot_search_stream_response

```{autodoc2-docstring} archivebox.search.views.snapshot_search_stream_response
```
````

````{py:function} admin_snapshot_search_stream_view(model_admin, request)
:canonical: archivebox.search.views.admin_snapshot_search_stream_view

```{autodoc2-docstring} archivebox.search.views.admin_snapshot_search_stream_view
```
````

````{py:function} public_snapshot_search_stream_view(request)
:canonical: archivebox.search.views.public_snapshot_search_stream_view

```{autodoc2-docstring} archivebox.search.views.public_snapshot_search_stream_view
```
````
