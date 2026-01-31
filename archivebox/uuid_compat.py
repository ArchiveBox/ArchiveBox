"""UUID7 compatibility layer for Python 3.13+

Python 3.14+ has native uuid7 support. For Python 3.13, we use uuid_extensions.

IMPORTANT: We also monkey-patch uuid.uuid7 for backward compatibility with
migrations that were auto-generated on Python 3.14+ systems.
"""

import sys
import uuid
import functools

if sys.version_info >= (3, 14):
    from uuid import uuid7 as _uuid7
else:
    try:
        from uuid_extensions import uuid7 as _uuid7
    except ImportError:
        raise ImportError(
            "uuid_extensions package is required for Python <3.14. "
            "Install it with: pip install uuid_extensions"
        )

    # Monkey-patch uuid module for migrations generated on Python 3.14+
    # that reference uuid.uuid7 directly
    if not hasattr(uuid, 'uuid7'):
        uuid.uuid7 = _uuid7


@functools.wraps(_uuid7)
def uuid7():
    """Generate a UUID7 (time-ordered UUID).

    This wrapper ensures Django migrations always reference
    'archivebox.uuid_compat.uuid7' regardless of Python version.
    """
    return _uuid7()


__all__ = ['uuid7']
