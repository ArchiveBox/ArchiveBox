__package__ = 'archivebox.index'

import re

from io import StringIO
from pathlib import Path
from typing import List, Tuple, Iterator
from django.db.models import QuerySet
from django.db import transaction

from archivebox.misc.util import enforce_types, parse_date
from archivebox.config import DATA_DIR
from archivebox.config.common import GENERAL_CONFIG

from .schema import Link

### Main Links Index

@enforce_types
def parse_sql_main_index(out_dir: Path=DATA_DIR) -> Iterator[Link]:
    from core.models import Snapshot

    return (
        Link.from_json(page.as_json(*Snapshot.keys))
        for page in Snapshot.objects.all()
    )

@enforce_types
def remove_from_sql_main_index(snapshots: QuerySet, atomic: bool=False, out_dir: Path=DATA_DIR) -> None:
    if atomic:
        with transaction.atomic():
            return snapshots.delete()
    return snapshots.delete()

@enforce_types
def write_link_to_sql_index(link: Link, created_by_id: int | None=None):
    from core.models import Snapshot, ArchiveResult
    from archivebox.base_models.models import get_or_create_system_user_pk

    info = {k: v for k, v in link._asdict().items() if k in Snapshot.keys}

    info['created_by_id'] = created_by_id or get_or_create_system_user_pk()

    tag_list = list(dict.fromkeys(
        tag.strip() for tag in re.split(GENERAL_CONFIG.TAG_SEPARATOR_PATTERN, link.tags or '')
    ))
    info.pop('tags')

    try:
        snapshot = Snapshot.objects.get(url=link.url)
        info["timestamp"] = snapshot.timestamp
    except Snapshot.DoesNotExist:
        while Snapshot.objects.filter(timestamp=info["timestamp"]).exists():
            info["timestamp"] = str(float(info["timestamp"]) + 1.0)

        snapshot, _ = Snapshot.objects.update_or_create(url=link.url, defaults=info)
    snapshot.save_tags(tag_list)

    for extractor, entries in link.history.items():
        for entry in entries:
            if isinstance(entry, dict):
                result, _ = ArchiveResult.objects.get_or_create(
                    snapshot_id=snapshot.pk,
                    extractor=extractor,
                    start_ts=parse_date(entry['start_ts']),
                    defaults={
                        'end_ts': parse_date(entry['end_ts']),
                        'cmd': entry['cmd'],
                        'output': entry['output'],
                        'cmd_version': entry.get('cmd_version') or 'unknown',
                        'pwd': entry['pwd'],
                        'status': entry['status'],
                        'created_by_id': snapshot.created_by_id,
                    }
                )
            else:
                result, _ = ArchiveResult.objects.update_or_create(
                    snapshot_id=snapshot.pk,
                    extractor=extractor,
                    start_ts=parse_date(entry.start_ts),
                    defaults={
                        'end_ts': parse_date(entry.end_ts),
                        'cmd': entry.cmd,
                        'output': entry.output,
                        'cmd_version': entry.cmd_version or 'unknown',
                        'pwd': entry.pwd,
                        'status': entry.status,
                        'created_by_id': snapshot.created_by_id,
                    }
                )

    return snapshot


@enforce_types
def write_sql_main_index(links: List[Link], out_dir: Path=DATA_DIR, created_by_id: int | None=None) -> None:
    for link in links:
        # with transaction.atomic():
            # write_link_to_sql_index(link)
        write_link_to_sql_index(link, created_by_id=created_by_id)
            

@enforce_types
def write_sql_link_details(link: Link, out_dir: Path=DATA_DIR, created_by_id: int | None=None) -> None:
    from core.models import Snapshot

    # with transaction.atomic():
    #     try:
    #         snap = Snapshot.objects.get(url=link.url)
    #     except Snapshot.DoesNotExist:
    #         snap = write_link_to_sql_index(link)
    #     snap.title = link.title
    try:
        snap = Snapshot.objects.get(url=link.url)
    except Snapshot.DoesNotExist:
        snap = write_link_to_sql_index(link, created_by_id=created_by_id)

    snap.title = link.title

    tag_list = list(
        {tag.strip() for tag in re.split(GENERAL_CONFIG.TAG_SEPARATOR_PATTERN, link.tags or '')}
        | set(snap.tags.values_list('name', flat=True))
    )

    snap.save()
    snap.save_tags(tag_list)



@enforce_types
def list_migrations(out_dir: Path=DATA_DIR) -> List[Tuple[bool, str]]:
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
def apply_migrations(out_dir: Path=DATA_DIR) -> List[str]:
    from django.core.management import call_command
    out1, out2 = StringIO(), StringIO()
    
    call_command("migrate", interactive=False, database='default', stdout=out1)
    out1.seek(0)
    call_command("migrate", "huey_monitor", interactive=False, database='queue', stdout=out2)
    out2.seek(0)

    return [
        line.strip() for line in out1.readlines() + out2.readlines() if line.strip()
    ]

@enforce_types
def get_admins(out_dir: Path=DATA_DIR) -> List[str]:
    from django.contrib.auth.models import User
    return User.objects.filter(is_superuser=True).exclude(username='system')
