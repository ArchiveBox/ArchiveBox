"""UUID7 compatibility layer."""

import sys
import uuid
from importlib import import_module

if sys.version_info >= (3, 14):
    _UUID7_GENERATOR = getattr(uuid, 'uuid7')
else:
    _UUID7_GENERATOR = getattr(import_module('uuid_extensions'), 'uuid7')


def uuid7() -> uuid.UUID:
    return _UUID7_GENERATOR()


__all__ = ['uuid7']
