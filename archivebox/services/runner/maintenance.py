from pathlib import Path
from django.utils import timezone


def run_snapshot_maintenance(snapshot_id: str, *, output_dir: Path | None = None) -> bool:
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
    if snapshot is None:
        return False

    # ArchiveBox owns filesystem and metadata maintenance at Snapshot
    # granularity. ArchiveResult rows are projections and never influence this
    # scheduler decision.
    current_retry_at = snapshot.retry_at
    has_pending_plugin_run = bool((snapshot.config or {}).get("RETRY_PLUGINS"))
    if snapshot.status == Snapshot.StatusChoices.SEALED and has_pending_plugin_run:
        next_retry_at = current_retry_at
    elif snapshot.status in Snapshot.OPEN_STATES:
        next_retry_at = timezone.now()
    else:
        next_retry_at = None
    if snapshot.fs_migration_needed:
        snapshot.migrate_filesystem_to_current_version()
    updated = snapshot.safe_update(
        {"retry_at": next_retry_at},
        refresh=False,
        extra_filter={
            "status": snapshot.status,
            "retry_at": current_retry_at,
        },
    )
    if not updated:
        return False
    snapshot.write_index_jsonl(output_dir=output_dir)
    return True
