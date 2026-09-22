# {py:mod}`archivebox.core.tag_util`

```{py:module} archivebox.core.tag_util
```

```{autodoc2-docstring} archivebox.core.tag_util
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`normalize_tag_name <archivebox.core.tag_util.normalize_tag_name>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.normalize_tag_name
    :summary:
    ```
* - {py:obj}`normalize_tag_sort <archivebox.core.tag_util.normalize_tag_sort>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.normalize_tag_sort
    :summary:
    ```
* - {py:obj}`normalize_has_snapshots_filter <archivebox.core.tag_util.normalize_has_snapshots_filter>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.normalize_has_snapshots_filter
    :summary:
    ```
* - {py:obj}`normalize_created_by_filter <archivebox.core.tag_util.normalize_created_by_filter>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.normalize_created_by_filter
    :summary:
    ```
* - {py:obj}`normalize_created_year_filter <archivebox.core.tag_util.normalize_created_year_filter>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.normalize_created_year_filter
    :summary:
    ```
* - {py:obj}`get_matching_tags <archivebox.core.tag_util.get_matching_tags>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.get_matching_tags
    :summary:
    ```
* - {py:obj}`add_snapshot_counts <archivebox.core.tag_util.add_snapshot_counts>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.add_snapshot_counts
    :summary:
    ```
* - {py:obj}`get_tag_creator_choices <archivebox.core.tag_util.get_tag_creator_choices>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.get_tag_creator_choices
    :summary:
    ```
* - {py:obj}`get_tag_year_choices <archivebox.core.tag_util.get_tag_year_choices>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.get_tag_year_choices
    :summary:
    ```
* - {py:obj}`get_tag_by_ref <archivebox.core.tag_util.get_tag_by_ref>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.get_tag_by_ref
    :summary:
    ```
* - {py:obj}`get_or_create_tag <archivebox.core.tag_util.get_or_create_tag>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.get_or_create_tag
    :summary:
    ```
* - {py:obj}`rename_tag <archivebox.core.tag_util.rename_tag>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.rename_tag
    :summary:
    ```
* - {py:obj}`delete_tag <archivebox.core.tag_util.delete_tag>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.delete_tag
    :summary:
    ```
* - {py:obj}`export_tag_urls <archivebox.core.tag_util.export_tag_urls>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.export_tag_urls
    :summary:
    ```
* - {py:obj}`export_tag_snapshots_jsonl <archivebox.core.tag_util.export_tag_snapshots_jsonl>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.export_tag_snapshots_jsonl
    :summary:
    ```
* - {py:obj}`_display_snapshot_title <archivebox.core.tag_util._display_snapshot_title>`
  - ```{autodoc2-docstring} archivebox.core.tag_util._display_snapshot_title
    :summary:
    ```
* - {py:obj}`_build_snapshot_preview <archivebox.core.tag_util._build_snapshot_preview>`
  - ```{autodoc2-docstring} archivebox.core.tag_util._build_snapshot_preview
    :summary:
    ```
* - {py:obj}`_build_snapshot_preview_map <archivebox.core.tag_util._build_snapshot_preview_map>`
  - ```{autodoc2-docstring} archivebox.core.tag_util._build_snapshot_preview_map
    :summary:
    ```
* - {py:obj}`build_tag_card <archivebox.core.tag_util.build_tag_card>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.build_tag_card
    :summary:
    ```
* - {py:obj}`build_tag_cards <archivebox.core.tag_util.build_tag_cards>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.build_tag_cards
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TAG_SNAPSHOT_PREVIEW_LIMIT <archivebox.core.tag_util.TAG_SNAPSHOT_PREVIEW_LIMIT>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.TAG_SNAPSHOT_PREVIEW_LIMIT
    :summary:
    ```
* - {py:obj}`TAG_SORT_CHOICES <archivebox.core.tag_util.TAG_SORT_CHOICES>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.TAG_SORT_CHOICES
    :summary:
    ```
* - {py:obj}`TAG_HAS_SNAPSHOTS_CHOICES <archivebox.core.tag_util.TAG_HAS_SNAPSHOTS_CHOICES>`
  - ```{autodoc2-docstring} archivebox.core.tag_util.TAG_HAS_SNAPSHOTS_CHOICES
    :summary:
    ```
````

### API

````{py:data} TAG_SNAPSHOT_PREVIEW_LIMIT
:canonical: archivebox.core.tag_util.TAG_SNAPSHOT_PREVIEW_LIMIT
:value: >
   10

```{autodoc2-docstring} archivebox.core.tag_util.TAG_SNAPSHOT_PREVIEW_LIMIT
```

````

````{py:data} TAG_SORT_CHOICES
:canonical: archivebox.core.tag_util.TAG_SORT_CHOICES
:value: >
   (('name_asc', 'Name A-Z'), ('name_desc', 'Name Z-A'), ('created_desc', 'Created newest'), ('created_...

```{autodoc2-docstring} archivebox.core.tag_util.TAG_SORT_CHOICES
```

````

````{py:data} TAG_HAS_SNAPSHOTS_CHOICES
:canonical: archivebox.core.tag_util.TAG_HAS_SNAPSHOTS_CHOICES
:value: >
   (('all', 'All'), ('yes', 'Has snapshots'), ('no', 'No snapshots'))

```{autodoc2-docstring} archivebox.core.tag_util.TAG_HAS_SNAPSHOTS_CHOICES
```

````

````{py:function} normalize_tag_name(name: str) -> str
:canonical: archivebox.core.tag_util.normalize_tag_name

```{autodoc2-docstring} archivebox.core.tag_util.normalize_tag_name
```
````

````{py:function} normalize_tag_sort(sort: str = 'created_desc') -> str
:canonical: archivebox.core.tag_util.normalize_tag_sort

```{autodoc2-docstring} archivebox.core.tag_util.normalize_tag_sort
```
````

````{py:function} normalize_has_snapshots_filter(value: str = 'all') -> str
:canonical: archivebox.core.tag_util.normalize_has_snapshots_filter

```{autodoc2-docstring} archivebox.core.tag_util.normalize_has_snapshots_filter
```
````

````{py:function} normalize_created_by_filter(created_by: str = '') -> str
:canonical: archivebox.core.tag_util.normalize_created_by_filter

```{autodoc2-docstring} archivebox.core.tag_util.normalize_created_by_filter
```
````

````{py:function} normalize_created_year_filter(year: str = '') -> str
:canonical: archivebox.core.tag_util.normalize_created_year_filter

```{autodoc2-docstring} archivebox.core.tag_util.normalize_created_year_filter
```
````

````{py:function} get_matching_tags(query: str = '', sort: str = 'created_desc', created_by: str = '', year: str = '', has_snapshots: str = 'all') -> django.db.models.QuerySet[archivebox.core.models.Tag]
:canonical: archivebox.core.tag_util.get_matching_tags

```{autodoc2-docstring} archivebox.core.tag_util.get_matching_tags
```
````

````{py:function} add_snapshot_counts(tags: list[archivebox.core.models.Tag], snapshot_queryset: django.db.models.QuerySet[archivebox.core.models.Snapshot] | None = None) -> None
:canonical: archivebox.core.tag_util.add_snapshot_counts

```{autodoc2-docstring} archivebox.core.tag_util.add_snapshot_counts
```
````

````{py:function} get_tag_creator_choices() -> list[tuple[str, str]]
:canonical: archivebox.core.tag_util.get_tag_creator_choices

```{autodoc2-docstring} archivebox.core.tag_util.get_tag_creator_choices
```
````

````{py:function} get_tag_year_choices() -> list[str]
:canonical: archivebox.core.tag_util.get_tag_year_choices

```{autodoc2-docstring} archivebox.core.tag_util.get_tag_year_choices
```
````

````{py:function} get_tag_by_ref(tag_ref: str | int) -> archivebox.core.models.Tag
:canonical: archivebox.core.tag_util.get_tag_by_ref

```{autodoc2-docstring} archivebox.core.tag_util.get_tag_by_ref
```
````

````{py:function} get_or_create_tag(name: str, created_by: django.contrib.auth.models.User | None = None) -> tuple[archivebox.core.models.Tag, bool]
:canonical: archivebox.core.tag_util.get_or_create_tag

```{autodoc2-docstring} archivebox.core.tag_util.get_or_create_tag
```
````

````{py:function} rename_tag(tag: archivebox.core.models.Tag, name: str) -> archivebox.core.models.Tag
:canonical: archivebox.core.tag_util.rename_tag

```{autodoc2-docstring} archivebox.core.tag_util.rename_tag
```
````

````{py:function} delete_tag(tag: archivebox.core.models.Tag) -> tuple[int, dict[str, int]]
:canonical: archivebox.core.tag_util.delete_tag

```{autodoc2-docstring} archivebox.core.tag_util.delete_tag
```
````

````{py:function} export_tag_urls(tag: archivebox.core.models.Tag) -> str
:canonical: archivebox.core.tag_util.export_tag_urls

```{autodoc2-docstring} archivebox.core.tag_util.export_tag_urls
```
````

````{py:function} export_tag_snapshots_jsonl(tag: archivebox.core.models.Tag) -> str
:canonical: archivebox.core.tag_util.export_tag_snapshots_jsonl

```{autodoc2-docstring} archivebox.core.tag_util.export_tag_snapshots_jsonl
```
````

````{py:function} _display_snapshot_title(snapshot: archivebox.core.models.Snapshot) -> str
:canonical: archivebox.core.tag_util._display_snapshot_title

```{autodoc2-docstring} archivebox.core.tag_util._display_snapshot_title
```
````

````{py:function} _build_snapshot_preview(snapshot: archivebox.core.models.Snapshot, request: django.http.HttpRequest | None = None, config: typing.Any | None = None) -> dict[str, typing.Any]
:canonical: archivebox.core.tag_util._build_snapshot_preview

```{autodoc2-docstring} archivebox.core.tag_util._build_snapshot_preview
```
````

````{py:function} _build_snapshot_preview_map(tags: list[archivebox.core.models.Tag], request: django.http.HttpRequest | None = None, preview_limit: int = TAG_SNAPSHOT_PREVIEW_LIMIT) -> dict[int, list[dict[str, typing.Any]]]
:canonical: archivebox.core.tag_util._build_snapshot_preview_map

```{autodoc2-docstring} archivebox.core.tag_util._build_snapshot_preview_map
```
````

````{py:function} build_tag_card(tag: archivebox.core.models.Tag, snapshot_previews: list[dict[str, typing.Any]] | None = None) -> dict[str, typing.Any]
:canonical: archivebox.core.tag_util.build_tag_card

```{autodoc2-docstring} archivebox.core.tag_util.build_tag_card
```
````

````{py:function} build_tag_cards(query: str = '', request: django.http.HttpRequest | None = None, limit: int | None = None, preview_limit: int = TAG_SNAPSHOT_PREVIEW_LIMIT, sort: str = 'created_desc', created_by: str = '', year: str = '', has_snapshots: str = 'all') -> list[dict[str, typing.Any]]
:canonical: archivebox.core.tag_util.build_tag_cards

```{autodoc2-docstring} archivebox.core.tag_util.build_tag_cards
```
````
