__package__ = "archivebox.core"

from django.db.models import QuerySet


def snapshot_status_values() -> tuple[str, ...]:
    from archivebox.core.models import Snapshot

    return tuple(Snapshot.StatusChoices.values)


def normalize_snapshot_status(status: str | None) -> str | None:
    value = str(status or "").strip().lower()
    if not value:
        return None

    valid_statuses = snapshot_status_values()
    if value not in valid_statuses:
        raise ValueError(f"Invalid snapshot status: {status}. Expected one of: {', '.join(valid_statuses)}")
    return value


def filter_snapshots_by_status(queryset: QuerySet, status: str | None) -> QuerySet:
    value = normalize_snapshot_status(status)
    return queryset.filter(status=value) if value else queryset
