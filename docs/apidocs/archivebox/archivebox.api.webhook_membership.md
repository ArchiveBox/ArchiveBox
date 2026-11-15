# {py:mod}`archivebox.api.webhook_membership`

```{py:module} archivebox.api.webhook_membership
```

```{autodoc2-docstring} archivebox.api.webhook_membership
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MembershipChange <archivebox.api.webhook_membership.MembershipChange>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.MembershipChange
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`track_membership <archivebox.api.webhook_membership.track_membership>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.track_membership
    :summary:
    ```
* - {py:obj}`related_snapshot_ids <archivebox.api.webhook_membership.related_snapshot_ids>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.related_snapshot_ids
    :summary:
    ```
* - {py:obj}`before_related_change <archivebox.api.webhook_membership.before_related_change>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.before_related_change
    :summary:
    ```
* - {py:obj}`after_related_change <archivebox.api.webhook_membership.after_related_change>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.after_related_change
    :summary:
    ```
* - {py:obj}`before_delete <archivebox.api.webhook_membership.before_delete>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.before_delete
    :summary:
    ```
* - {py:obj}`after_delete <archivebox.api.webhook_membership.after_delete>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.after_delete
    :summary:
    ```
* - {py:obj}`tags_changed <archivebox.api.webhook_membership.tags_changed>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.tags_changed
    :summary:
    ```
* - {py:obj}`register_membership_signals <archivebox.api.webhook_membership.register_membership_signals>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership.register_membership_signals
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_active <archivebox.api.webhook_membership._active>`
  - ```{autodoc2-docstring} archivebox.api.webhook_membership._active
    :summary:
    ```
````

### API

````{py:data} _active
:canonical: archivebox.api.webhook_membership._active
:value: >
   'ContextVar(...)'

```{autodoc2-docstring} archivebox.api.webhook_membership._active
```

````

`````{py:class} MembershipChange(snapshot_ids=None, *, deleted=None)
:canonical: archivebox.api.webhook_membership.MembershipChange

```{autodoc2-docstring} archivebox.api.webhook_membership.MembershipChange
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.webhook_membership.MembershipChange.__init__
```

````{py:method} finish()
:canonical: archivebox.api.webhook_membership.MembershipChange.finish

```{autodoc2-docstring} archivebox.api.webhook_membership.MembershipChange.finish
```

````

`````

````{py:function} track_membership(snapshot_ids=None, *, deleted=None)
:canonical: archivebox.api.webhook_membership.track_membership

```{autodoc2-docstring} archivebox.api.webhook_membership.track_membership
```
````

````{py:function} related_snapshot_ids(instance)
:canonical: archivebox.api.webhook_membership.related_snapshot_ids

```{autodoc2-docstring} archivebox.api.webhook_membership.related_snapshot_ids
```
````

````{py:function} before_related_change(sender, instance, raw=False, **kwargs)
:canonical: archivebox.api.webhook_membership.before_related_change

```{autodoc2-docstring} archivebox.api.webhook_membership.before_related_change
```
````

````{py:function} after_related_change(sender, instance, **kwargs)
:canonical: archivebox.api.webhook_membership.after_related_change

```{autodoc2-docstring} archivebox.api.webhook_membership.after_related_change
```
````

````{py:function} before_delete(sender, instance, origin=None, **kwargs)
:canonical: archivebox.api.webhook_membership.before_delete

```{autodoc2-docstring} archivebox.api.webhook_membership.before_delete
```
````

````{py:function} after_delete(sender, instance, origin=None, **kwargs)
:canonical: archivebox.api.webhook_membership.after_delete

```{autodoc2-docstring} archivebox.api.webhook_membership.after_delete
```
````

````{py:function} tags_changed(sender, instance, action, reverse, pk_set, **kwargs)
:canonical: archivebox.api.webhook_membership.tags_changed

```{autodoc2-docstring} archivebox.api.webhook_membership.tags_changed
```
````

````{py:function} register_membership_signals()
:canonical: archivebox.api.webhook_membership.register_membership_signals

```{autodoc2-docstring} archivebox.api.webhook_membership.register_membership_signals
```
````
