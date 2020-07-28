__package__ = 'archivebox.index'

from io import StringIO
from typing import List, Tuple, Iterator

from .schema import Link
from ..util import enforce_types
from ..config import setup_django, OUTPUT_DIR


### Main Links Index

@enforce_types
def parse_sql_main_index(out_dir: str=OUTPUT_DIR) -> Iterator[Link]:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot

    return (
        Link.from_json(page.as_json(*Snapshot.keys))
        for page in Snapshot.objects.all()
    )

@enforce_types
def remove_from_sql_main_index(links: List[Link], out_dir: str=OUTPUT_DIR) -> None:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot
    from django.db import transaction

    with transaction.atomic():
        for link in links:
            Snapshot.objects.filter(url=link.url).delete()

@enforce_types
def write_sql_main_index(links: List[Link], out_dir: str=OUTPUT_DIR) -> None:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot
    from django.db import transaction

    with transaction.atomic():
        for link in links:
            info = {k: v for k, v in link._asdict().items() if k in Snapshot.keys}
            Snapshot.objects.update_or_create(url=link.url, defaults=info)

@enforce_types
def write_sql_link_details(link: Link, out_dir: str=OUTPUT_DIR) -> None:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot
    from django.db import transaction

    with transaction.atomic():
        snap = Snapshot.objects.get(url=link.url, timestamp=link.timestamp)
        snap.title = link.title
        snap.tags = link.tags
        snap.save()



@enforce_types
def list_migrations(out_dir: str=OUTPUT_DIR) -> List[Tuple[bool, str]]:
    setup_django(out_dir, check_db=False)
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
def apply_migrations(out_dir: str=OUTPUT_DIR) -> List[str]:
    setup_django(out_dir, check_db=False)
    from django.core.management import call_command
    null, out = StringIO(), StringIO()
    call_command("makemigrations", interactive=False, stdout=null)
    call_command("migrate", interactive=False, stdout=out)
    out.seek(0)

    return [line.strip() for line in out.readlines() if line.strip()]

@enforce_types
def get_admins(out_dir: str=OUTPUT_DIR) -> List[str]:
    setup_django(out_dir, check_db=False)
    from django.contrib.auth.models import User
    return User.objects.filter(is_superuser=True)
