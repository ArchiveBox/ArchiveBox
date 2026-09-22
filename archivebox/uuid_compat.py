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
        return CompactUUID(hex=value.hex)
    return CompactUUID(str(value))


class CompactUUIDField(models.UUIDField):
    def to_python(self, value):
        return compact_uuid(super().to_python(value))

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, "django.db.models.UUIDField", args, kwargs


def uuid7() -> CompactUUID:
    value = compact_uuid(_UUID7_GENERATOR())
    assert value is not None
    return value


__all__ = ["CompactUUID", "CompactUUIDField", "compact_uuid", "uuid7"]
