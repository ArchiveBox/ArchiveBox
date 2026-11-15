"""UUID7 compatibility layer."""

import sys
import uuid
from importlib import import_module

from django.db import models

if sys.version_info >= (3, 14):
    _UUID7_GENERATOR = getattr(uuid, "uuid7")
else:
    _UUID7_GENERATOR = getattr(import_module("uuid_extensions"), "uuid7")


class CompactUUID(uuid.UUID):
    def __str__(self) -> str:
        return self.hex


def compact_uuid(value: uuid.UUID | str | None) -> CompactUUID | None:
    if value is None:
        return None
    if isinstance(value, CompactUUID):
        return value
    if isinstance(value, uuid.UUID):
        # ORM reads already decoded the UUID. Reuse its integer instead of
        # formatting and parsing hex again for every primary/foreign key.
        return CompactUUID(int=value.int)
    return CompactUUID(str(value))


class CompactUUIDField(models.UUIDField):
    def to_python(self, value):
        if value is None or isinstance(value, CompactUUID):
            return value
        return compact_uuid(super().to_python(value))

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, "django.db.models.UUIDField", args, kwargs


@models.UUIDField.register_lookup
class UUIDSuffix(models.Transform):
    """Indexable snapshot-host suffix for both native and text UUID storage."""

    lookup_name = "suffix"
    output_field = models.CharField(max_length=12)
    # Keep the length literal identical in the index and parameterized queries.
    template = "RIGHT(CAST(%(expressions)s AS TEXT), 12)"

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, template="SUBSTR(CAST(%(expressions)s AS TEXT), -12)", **extra_context)


def uuid7() -> CompactUUID:
    value = compact_uuid(_UUID7_GENERATOR())
    assert value is not None
    return value


__all__ = ["CompactUUID", "CompactUUIDField", "compact_uuid", "uuid7"]
