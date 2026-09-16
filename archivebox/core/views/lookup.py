from pathlib import Path

from archivebox.core.models import Snapshot
from archivebox.core.routes_util import (
    get_snapshot_lookup_key,
)


def _files_index_target(snapshot: Snapshot, archivefile: str | None) -> str:
    target = archivefile or ""
    if target == "index.html":
        target = ""
    fullpath = Path(snapshot.output_dir) / target
    if fullpath.is_file():
        target = str(Path(target).parent)
        if target == ".":
            target = ""
    return target


def _find_snapshot_by_ref(snapshot_ref: str) -> Snapshot | None:
    lookup = get_snapshot_lookup_key(snapshot_ref)
    if not lookup:
        return None

    snapshots = Snapshot.objects.select_related("crawl", "crawl__created_by")

    if len(lookup) == 12 and "-" not in lookup:
        return snapshots.filter(id__endswith=lookup).order_by("-created_at", "-downloaded_at").first()

    try:
        return snapshots.get(pk=lookup)
    except Snapshot.DoesNotExist:
        try:
            return snapshots.get(id__startswith=lookup)
        except Snapshot.DoesNotExist:
            return None
        except Snapshot.MultipleObjectsReturned:
            return snapshots.filter(id__startswith=lookup).first()
