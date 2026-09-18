"""
Shared CLI utilities for ArchiveBox commands.

This module contains common utilities used across multiple CLI commands,
extracted to avoid code duplication.
"""

__package__ = "archivebox.cli"


def apply_filters(queryset, filter_kwargs: dict, limit: int | None = None):
    """
    Apply Django-style filters from CLI kwargs to a QuerySet.

    Supports: --status=queued, --url__icontains=example, --id__in=uuid1,uuid2

    Args:
        queryset: Django QuerySet to filter
        filter_kwargs: Dict of filter key-value pairs from CLI
        limit: Optional limit on results

    Returns:
        Filtered QuerySet

    Example:
        queryset = Snapshot.objects.all()
        filter_kwargs = {'status': 'queued', 'url__icontains': 'example.com'}
        filtered = apply_filters(queryset, filter_kwargs, limit=10)
    """
    filters = {}
    for key, value in filter_kwargs.items():
        if value is None or key in ("limit", "offset"):
            continue
        # Handle CSV lists for __in filters
        if key.endswith("__in") and isinstance(value, str):
            value = [v.strip() for v in value.split(",")]
        filters[key] = value

    if filters:
        queryset = queryset.filter(**filters)
    if limit:
        queryset = queryset[:limit]

    return queryset


def delete_records(
    model,
    *,
    label: str,
    plural: str,
    preview,
    yes: bool,
    dry_run: bool,
    preview_limit: int | None = None,
    by_name: bool = False,
) -> int:
    """Delete a JSONL selection with one confirmation and dry-run contract.

    Keep queryset deletion so Django's cascades and model cleanup signals run.
    Persona deletion has additional filesystem policy and stays with that command.
    """
    import sys

    from django.db.models import Q
    from rich import print as rprint

    from archivebox.misc.jsonl import read_stdin

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1
    ids = [record["id"] for record in records if record.get("id")]
    names = [record["name"] for record in records if by_name and not record.get("id") and record.get("name")]
    if not ids and not names:
        rprint(f"[yellow]No valid {label} IDs{' or names' if by_name else ''} in input[/yellow]", file=sys.stderr)
        return 1
    query = Q(id__in=ids)
    if names:
        query |= Q(name__in=names)
    queryset = model.objects.filter(query)
    count = queryset.count()
    if not count:
        rprint(f"[yellow]No matching {plural} found[/yellow]", file=sys.stderr)
        return 0
    if dry_run:
        rprint(f"[yellow]Would delete {count} {plural} (dry run)[/yellow]", file=sys.stderr)
        for obj in queryset[:preview_limit] if preview_limit is not None else queryset:
            rprint(f"  {preview(obj)}", file=sys.stderr)
        if preview_limit is not None and count > preview_limit:
            rprint(f"  ... and {count - preview_limit} more", file=sys.stderr)
        return 0
    if not yes:
        rprint("[red]Use --yes to confirm deletion[/red]", file=sys.stderr)
        return 1
    deleted_count, _ = queryset.delete()
    rprint(f"[green]Deleted {deleted_count} {plural}[/green]", file=sys.stderr)
    return 0


def update_record_status(record, status: str) -> None:
    """Route CLI status changes through the model's lifecycle operations."""
    from django.utils import timezone

    if status not in record.StatusChoices.values:
        raise ValueError(f"Invalid {record._meta.model_name} status: {status}")
    transitions = {"sealed": record.cancel, "paused": record.pause}
    if status == "queued" and record.is_paused:
        record.resume()
    elif transition := transitions.get(status):
        transition()
    else:
        record.update_and_requeue(status=status, retry_at=timezone.now())


def list_records(queryset, *, plural: str, render) -> int:
    """Stream JSONL when piped; render rows and a count in a terminal."""
    import sys
    from rich import print as rprint
    from archivebox.misc.jsonl import write_record

    is_tty = sys.stdout.isatty()
    count = 0
    for record in queryset:
        if is_tty:
            rprint(render(record))
        else:
            write_record(record.to_json())
        count += 1
    rprint(f"[dim]Listed {count} {plural}[/dim]", file=sys.stderr)
    return 0


def format_status(status: str, width: int) -> str:
    colors = {
        "queued": "yellow",
        "started": "blue",
        "sealed": "green",
        "succeeded": "green",
        "failed": "red",
        "backoff": "magenta",
    }
    color = colors.get(status, "dim")
    return f"[{color}]{status:{width}}[/{color}]"


def update_records(model, update, *, plural: str, by_name: bool = False, refresh: bool = False) -> int:
    """Apply a command's PATCH operation to each JSONL-selected model.

    Returning False from the operation skips that row. Model operations stay in
    their commands so lifecycle changes and ordinary field saves remain explicit.
    """
    import sys
    from rich import print as rprint
    from archivebox.misc.jsonl import read_stdin, write_record

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1
    is_tty = sys.stdout.isatty()
    count = 0
    for record in records:
        key = "id" if record.get("id") else "name" if by_name and record.get("name") else None
        if key is None:
            continue
        try:
            obj = model.objects.get(**{key: record[key]})
            if update(obj) is False:
                continue
            count += 1
            if not is_tty:
                if refresh:
                    obj.refresh_from_db()
                write_record(obj.to_json())
        except model.DoesNotExist:
            rprint(f"[yellow]{model.__name__} not found: {record[key]}[/yellow]", file=sys.stderr)
    rprint(f"[green]Updated {count} {plural}[/green]", file=sys.stderr)
    return 0
