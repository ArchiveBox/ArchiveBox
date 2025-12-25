"""
Database utility functions for ArchiveBox.
"""

__package__ = 'archivebox.misc'

from io import StringIO
from pathlib import Path
from typing import List, Tuple

from archivebox.config import DATA_DIR
from archivebox.misc.util import enforce_types


@enforce_types
def list_migrations(out_dir: Path = DATA_DIR) -> List[Tuple[bool, str]]:
    """List all Django migrations and their status"""
    from django.core.management import call_command

    out = StringIO()
    call_command("showmigrations", list=True, stdout=out)
    out.seek(0)

    migrations = []
    for line in out.readlines():
        if line.strip() and ']' in line:
            status_str, name_str = line.strip().split(']', 1)
            is_applied = 'X' in status_str
            migration_name = name_str.strip()
            migrations.append((is_applied, migration_name))

    return migrations


@enforce_types
def apply_migrations(out_dir: Path = DATA_DIR) -> List[str]:
    """Apply pending Django migrations"""
    from django.core.management import call_command

    out1 = StringIO()

    call_command("migrate", interactive=False, database='default', stdout=out1)
    out1.seek(0)

    return [
        line.strip() for line in out1.readlines() if line.strip()
    ]


@enforce_types
def get_admins(out_dir: Path = DATA_DIR) -> List:
    """Get list of superuser accounts"""
    from django.contrib.auth.models import User

    return User.objects.filter(is_superuser=True).exclude(username='system')
