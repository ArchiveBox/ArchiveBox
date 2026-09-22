# {py:mod}`archivebox.core.permissions`

```{py:module} archivebox.core.permissions
```

```{autodoc2-docstring} archivebox.core.permissions
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`normalize_permissions <archivebox.core.permissions.normalize_permissions>`
  - ```{autodoc2-docstring} archivebox.core.permissions.normalize_permissions
    :summary:
    ```
* - {py:obj}`is_admin_user <archivebox.core.permissions.is_admin_user>`
  - ```{autodoc2-docstring} archivebox.core.permissions.is_admin_user
    :summary:
    ```
* - {py:obj}`get_snapshot_permissions <archivebox.core.permissions.get_snapshot_permissions>`
  - ```{autodoc2-docstring} archivebox.core.permissions.get_snapshot_permissions
    :summary:
    ```
* - {py:obj}`can_view_snapshot <archivebox.core.permissions.can_view_snapshot>`
  - ```{autodoc2-docstring} archivebox.core.permissions.can_view_snapshot
    :summary:
    ```
* - {py:obj}`_persona_ids_for_permissions <archivebox.core.permissions._persona_ids_for_permissions>`
  - ```{autodoc2-docstring} archivebox.core.permissions._persona_ids_for_permissions
    :summary:
    ```
* - {py:obj}`filter_personas_by_permissions <archivebox.core.permissions.filter_personas_by_permissions>`
  - ```{autodoc2-docstring} archivebox.core.permissions.filter_personas_by_permissions
    :summary:
    ```
* - {py:obj}`filter_snapshots_by_permissions <archivebox.core.permissions.filter_snapshots_by_permissions>`
  - ```{autodoc2-docstring} archivebox.core.permissions.filter_snapshots_by_permissions
    :summary:
    ```
* - {py:obj}`public_snapshots_queryset <archivebox.core.permissions.public_snapshots_queryset>`
  - ```{autodoc2-docstring} archivebox.core.permissions.public_snapshots_queryset
    :summary:
    ```
* - {py:obj}`direct_snapshots_queryset <archivebox.core.permissions.direct_snapshots_queryset>`
  - ```{autodoc2-docstring} archivebox.core.permissions.direct_snapshots_queryset
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PERMISSIONS_PUBLIC <archivebox.core.permissions.PERMISSIONS_PUBLIC>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_PUBLIC
    :summary:
    ```
* - {py:obj}`PERMISSIONS_UNLISTED <archivebox.core.permissions.PERMISSIONS_UNLISTED>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_UNLISTED
    :summary:
    ```
* - {py:obj}`PERMISSIONS_PRIVATE <archivebox.core.permissions.PERMISSIONS_PRIVATE>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_PRIVATE
    :summary:
    ```
* - {py:obj}`PERMISSIONS_CHOICES <archivebox.core.permissions.PERMISSIONS_CHOICES>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_CHOICES
    :summary:
    ```
* - {py:obj}`PERMISSIONS_VALUES <archivebox.core.permissions.PERMISSIONS_VALUES>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_VALUES
    :summary:
    ```
* - {py:obj}`PERMISSIONS_META <archivebox.core.permissions.PERMISSIONS_META>`
  - ```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_META
    :summary:
    ```
````

### API

````{py:data} PERMISSIONS_PUBLIC
:canonical: archivebox.core.permissions.PERMISSIONS_PUBLIC
:value: >
   'public'

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_PUBLIC
```

````

````{py:data} PERMISSIONS_UNLISTED
:canonical: archivebox.core.permissions.PERMISSIONS_UNLISTED
:value: >
   'unlisted'

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_UNLISTED
```

````

````{py:data} PERMISSIONS_PRIVATE
:canonical: archivebox.core.permissions.PERMISSIONS_PRIVATE
:value: >
   'private'

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_PRIVATE
```

````

````{py:data} PERMISSIONS_CHOICES
:canonical: archivebox.core.permissions.PERMISSIONS_CHOICES
:value: >
   ((), (), ())

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_CHOICES
```

````

````{py:data} PERMISSIONS_VALUES
:canonical: archivebox.core.permissions.PERMISSIONS_VALUES
:value: >
   None

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_VALUES
```

````

````{py:data} PERMISSIONS_META
:canonical: archivebox.core.permissions.PERMISSIONS_META
:value: >
   None

```{autodoc2-docstring} archivebox.core.permissions.PERMISSIONS_META
```

````

````{py:function} normalize_permissions(permissions: object, *, default: str = PERMISSIONS_PRIVATE) -> str
:canonical: archivebox.core.permissions.normalize_permissions

```{autodoc2-docstring} archivebox.core.permissions.normalize_permissions
```
````

````{py:function} is_admin_user(request: django.http.HttpRequest) -> bool
:canonical: archivebox.core.permissions.is_admin_user

```{autodoc2-docstring} archivebox.core.permissions.is_admin_user
```
````

````{py:function} get_snapshot_permissions(snapshot) -> str
:canonical: archivebox.core.permissions.get_snapshot_permissions

```{autodoc2-docstring} archivebox.core.permissions.get_snapshot_permissions
```
````

````{py:function} can_view_snapshot(request: django.http.HttpRequest, snapshot) -> bool
:canonical: archivebox.core.permissions.can_view_snapshot

```{autodoc2-docstring} archivebox.core.permissions.can_view_snapshot
```
````

````{py:function} _persona_ids_for_permissions(allowed_permissions: set[str]) -> list[str]
:canonical: archivebox.core.permissions._persona_ids_for_permissions

```{autodoc2-docstring} archivebox.core.permissions._persona_ids_for_permissions
```
````

````{py:function} filter_personas_by_permissions(queryset: django.db.models.QuerySet, allowed_permissions: set[str]) -> django.db.models.QuerySet
:canonical: archivebox.core.permissions.filter_personas_by_permissions

```{autodoc2-docstring} archivebox.core.permissions.filter_personas_by_permissions
```
````

````{py:function} filter_snapshots_by_permissions(queryset: django.db.models.QuerySet, *, direct: bool = False, allowed_permissions: set[str] | None = None) -> django.db.models.QuerySet
:canonical: archivebox.core.permissions.filter_snapshots_by_permissions

```{autodoc2-docstring} archivebox.core.permissions.filter_snapshots_by_permissions
```
````

````{py:function} public_snapshots_queryset(queryset: django.db.models.QuerySet) -> django.db.models.QuerySet
:canonical: archivebox.core.permissions.public_snapshots_queryset

```{autodoc2-docstring} archivebox.core.permissions.public_snapshots_queryset
```
````

````{py:function} direct_snapshots_queryset(request: django.http.HttpRequest, queryset: django.db.models.QuerySet) -> django.db.models.QuerySet
:canonical: archivebox.core.permissions.direct_snapshots_queryset

```{autodoc2-docstring} archivebox.core.permissions.direct_snapshots_queryset
```
````
