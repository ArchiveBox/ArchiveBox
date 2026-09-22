# {py:mod}`archivebox.uuid_compat`

```{py:module} archivebox.uuid_compat
```

```{autodoc2-docstring} archivebox.uuid_compat
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CompactUUID <archivebox.uuid_compat.CompactUUID>`
  -
* - {py:obj}`CompactUUIDField <archivebox.uuid_compat.CompactUUIDField>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`compact_uuid <archivebox.uuid_compat.compact_uuid>`
  - ```{autodoc2-docstring} archivebox.uuid_compat.compact_uuid
    :summary:
    ```
* - {py:obj}`uuid7 <archivebox.uuid_compat.uuid7>`
  - ```{autodoc2-docstring} archivebox.uuid_compat.uuid7
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__all__ <archivebox.uuid_compat.__all__>`
  - ```{autodoc2-docstring} archivebox.uuid_compat.__all__
    :summary:
    ```
````

### API

`````{py:class} CompactUUID(hex=None, bytes=None, bytes_le=None, fields=None, int=None, version=None, *, is_safe=SafeUUID.unknown)
:canonical: archivebox.uuid_compat.CompactUUID

Bases: {py:obj}`uuid.UUID`

````{py:method} __str__() -> str
:canonical: archivebox.uuid_compat.CompactUUID.__str__

````

`````

````{py:function} compact_uuid(value: uuid.UUID | str | None) -> archivebox.uuid_compat.CompactUUID | None
:canonical: archivebox.uuid_compat.compact_uuid

```{autodoc2-docstring} archivebox.uuid_compat.compact_uuid
```
````

`````{py:class} CompactUUIDField(verbose_name=None, **kwargs)
:canonical: archivebox.uuid_compat.CompactUUIDField

Bases: {py:obj}`django.db.models.UUIDField`

````{py:method} to_python(value)
:canonical: archivebox.uuid_compat.CompactUUIDField.to_python

````

````{py:method} from_db_value(value, expression, connection)
:canonical: archivebox.uuid_compat.CompactUUIDField.from_db_value

```{autodoc2-docstring} archivebox.uuid_compat.CompactUUIDField.from_db_value
```

````

````{py:method} deconstruct()
:canonical: archivebox.uuid_compat.CompactUUIDField.deconstruct

````

`````

````{py:function} uuid7() -> archivebox.uuid_compat.CompactUUID
:canonical: archivebox.uuid_compat.uuid7

```{autodoc2-docstring} archivebox.uuid_compat.uuid7
```
````

````{py:data} __all__
:canonical: archivebox.uuid_compat.__all__
:value: >
   ['CompactUUID', 'CompactUUIDField', 'compact_uuid', 'uuid7']

```{autodoc2-docstring} archivebox.uuid_compat.__all__
```

````
