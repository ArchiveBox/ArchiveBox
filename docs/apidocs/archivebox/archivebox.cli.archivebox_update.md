# {py:mod}`archivebox.cli.archivebox_update`

```{py:module} archivebox.cli.archivebox_update
```

```{autodoc2-docstring} archivebox.cli.archivebox_update
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_get_snapshot_crawl <archivebox.cli.archivebox_update._get_snapshot_crawl>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update._get_snapshot_crawl
    :summary:
    ```
* - {py:obj}`_get_search_indexing_plugins <archivebox.cli.archivebox_update._get_search_indexing_plugins>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update._get_search_indexing_plugins
    :summary:
    ```
* - {py:obj}`_build_filtered_snapshots_queryset <archivebox.cli.archivebox_update._build_filtered_snapshots_queryset>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update._build_filtered_snapshots_queryset
    :summary:
    ```
* - {py:obj}`reindex_snapshots <archivebox.cli.archivebox_update.reindex_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.reindex_snapshots
    :summary:
    ```
* - {py:obj}`update <archivebox.cli.archivebox_update.update>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.update
    :summary:
    ```
* - {py:obj}`drain_old_archive_dirs <archivebox.cli.archivebox_update.drain_old_archive_dirs>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.drain_old_archive_dirs
    :summary:
    ```
* - {py:obj}`process_all_db_snapshots <archivebox.cli.archivebox_update.process_all_db_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.process_all_db_snapshots
    :summary:
    ```
* - {py:obj}`process_filtered_snapshots <archivebox.cli.archivebox_update.process_filtered_snapshots>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.process_filtered_snapshots
    :summary:
    ```
* - {py:obj}`print_stats <archivebox.cli.archivebox_update.print_stats>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.print_stats
    :summary:
    ```
* - {py:obj}`print_combined_stats <archivebox.cli.archivebox_update.print_combined_stats>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.print_combined_stats
    :summary:
    ```
* - {py:obj}`print_index_stats <archivebox.cli.archivebox_update.print_index_stats>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.print_index_stats
    :summary:
    ```
* - {py:obj}`main <archivebox.cli.archivebox_update.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_update.main
    :summary:
    ```
````

### API

````{py:function} _get_snapshot_crawl(snapshot: archivebox.core.models.Snapshot) -> archivebox.crawls.models.Crawl | None
:canonical: archivebox.cli.archivebox_update._get_snapshot_crawl

```{autodoc2-docstring} archivebox.cli.archivebox_update._get_snapshot_crawl
```
````

````{py:function} _get_search_indexing_plugins() -> list[str]
:canonical: archivebox.cli.archivebox_update._get_search_indexing_plugins

```{autodoc2-docstring} archivebox.cli.archivebox_update._get_search_indexing_plugins
```
````

````{py:function} _build_filtered_snapshots_queryset(**kwargs)
:canonical: archivebox.cli.archivebox_update._build_filtered_snapshots_queryset

```{autodoc2-docstring} archivebox.cli.archivebox_update._build_filtered_snapshots_queryset
```
````

````{py:function} reindex_snapshots(snapshots: django.db.models.QuerySet[archivebox.core.models.Snapshot, archivebox.core.models.Snapshot], *, search_plugins: list[str], batch_size: int, collect_ids: bool = False, wait_for_turn=None) -> dict[str, typing.Any]
:canonical: archivebox.cli.archivebox_update.reindex_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_update.reindex_snapshots
```
````

````{py:function} update(filter_patterns: collections.abc.Iterable[str] = (), filter_type: str = 'exact', status: str | None = None, url__icontains: str | None = None, url__istartswith: str | None = None, tag: str | None = None, crawl_id: str | None = None, limit: int | None = None, sort: str | None = None, search: str | None = None, before: float | None = None, after: float | None = None, resume: str | None = None, batch_size: int = 500, continuous: bool = False, index_only: bool = False, migrate_only: bool = False, stop_daemon_stack: bool = True) -> None
:canonical: archivebox.cli.archivebox_update.update

```{autodoc2-docstring} archivebox.cli.archivebox_update.update
```
````

````{py:function} drain_old_archive_dirs(resume_from: str | None = None, batch_size: int = 500) -> dict[str, int]
:canonical: archivebox.cli.archivebox_update.drain_old_archive_dirs

```{autodoc2-docstring} archivebox.cli.archivebox_update.drain_old_archive_dirs
```
````

````{py:function} process_all_db_snapshots(batch_size: int = 500, resume: str | None = None, wait_for_turn=None) -> dict[str, int]
:canonical: archivebox.cli.archivebox_update.process_all_db_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_update.process_all_db_snapshots
```
````

````{py:function} process_filtered_snapshots(filter_patterns: collections.abc.Iterable[str], filter_type: str, status: str | None, url__icontains: str | None, url__istartswith: str | None, tag: str | None, crawl_id: str | None, limit: int | None, sort: str | None, search: str | None, before: float | None, after: float | None, resume: str | None, batch_size: int, queue_for_archiving: bool = True, wait_for_turn=None) -> dict[str, typing.Any]
:canonical: archivebox.cli.archivebox_update.process_filtered_snapshots

```{autodoc2-docstring} archivebox.cli.archivebox_update.process_filtered_snapshots
```
````

````{py:function} print_stats(stats: dict)
:canonical: archivebox.cli.archivebox_update.print_stats

```{autodoc2-docstring} archivebox.cli.archivebox_update.print_stats
```
````

````{py:function} print_combined_stats(stats_combined: dict)
:canonical: archivebox.cli.archivebox_update.print_combined_stats

```{autodoc2-docstring} archivebox.cli.archivebox_update.print_combined_stats
```
````

````{py:function} print_index_stats(stats: dict[str, typing.Any]) -> None
:canonical: archivebox.cli.archivebox_update.print_index_stats

```{autodoc2-docstring} archivebox.cli.archivebox_update.print_index_stats
```
````

````{py:function} main(**kwargs)
:canonical: archivebox.cli.archivebox_update.main

```{autodoc2-docstring} archivebox.cli.archivebox_update.main
```
````
