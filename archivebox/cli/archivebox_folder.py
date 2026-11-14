"""Manage folders, smart rules, and snapshot membership."""

import json

import rich_click as click

from archivebox.misc.jsonl import write_record, write_record_table


@click.group()
def main():
    """Manage folders and smart folders."""


@main.command("list")
@click.option("--format", type=click.Choice(["jsonl", "json", "csv", "tsv"]), default="jsonl")
def list_folders(format):
    """List folders with rules, parent IDs and names."""
    from archivebox.core.models import Folder

    write_record_table((folder.to_json() for folder in Folder.objects.select_related("parent", "created_by")), format=format)


@main.command("get")
@click.argument("folder_id", type=click.UUID)
def get_folder(folder_id):
    """Read one folder."""
    from archivebox.core.models import Folder

    try:
        folder = Folder.objects.get(pk=folder_id)
    except Folder.DoesNotExist as error:
        raise click.ClickException(f"Folder not found: {folder_id}") from error
    write_record(folder.to_json())


@main.command("create")
@click.argument("name")
@click.option("--parent-id", type=click.UUID)
@click.option("--rules", help="JSON smart-folder rule tree; omit for a regular folder.")
@click.option("--position", type=click.IntRange(min=0), default=0)
def create_folder(name, parent_id, rules, position):
    """Create a regular or smart folder using native rule validation."""
    from django.core.exceptions import ValidationError
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Folder

    try:
        folder = Folder.objects.create(
            name=name,
            parent_id=parent_id,
            rules=json.loads(rules) if rules else None,
            position=position,
            created_by_id=get_or_create_system_user_pk(),
        )
    except (ValueError, ValidationError) as error:
        raise click.ClickException(str(error)) from error
    folder.refresh_from_db()
    write_record(folder.to_json())


@main.command("update")
@click.argument("folder_id", type=click.UUID)
@click.option("--data", required=True, help="JSON fields: name, parent_id (null for root), position, rules.")
def update_folder(folder_id, data):
    """Rename, move, reorder, or replace a smart folder's rules."""
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder

    try:
        folder = Folder.objects.get(pk=folder_id)
        values = json.loads(data)
        if not isinstance(values, dict) or set(values) - {"name", "parent_id", "position", "rules"}:
            raise ValueError("Use name, parent_id, position, or rules.")
        if values.get("parent_id") is not None and not isinstance(values["parent_id"], str):
            raise ValueError("parent_id must be a UUID string or null.")
        for key, value in values.items():
            setattr(folder, key, value)
        folder.save()
    except Folder.DoesNotExist as error:
        raise click.ClickException(f"Folder not found: {folder_id}") from error
    except (ValueError, ValidationError) as error:
        raise click.ClickException(str(error)) from error
    folder.refresh_from_db()
    write_record(folder.to_json())


@main.command("delete")
@click.argument("folder_id", type=click.UUID)
@click.option("--yes", is_flag=True, required=True, help="Confirm folder deletion; captures are preserved.")
def delete_folder(folder_id, yes):
    """Delete folder metadata while preserving captures and child folders."""
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder

    try:
        Folder.objects.get(pk=folder_id).delete()
    except Folder.DoesNotExist as error:
        raise click.ClickException(f"Folder not found: {folder_id}") from error
    except ValidationError as error:
        raise click.ClickException(str(error)) from error
    write_record({"deleted": True, "id": folder_id.hex})


@main.command("rules")
def rule_schema():
    """Show supported smart rule fields, operators and sorting."""
    from archivebox.core.smart_folders import OPERATORS, RuleQuery

    write_record({"fields": RuleQuery.schema(), "operators": OPERATORS, "sort_fields": RuleQuery.sort_fields()})


@main.command("move-snapshots")
@click.argument("snapshot_ids", type=click.UUID, nargs=-1, required=True)
@click.option("--destination-id", type=click.UUID, help="Destination folder; omit to unfile.")
def move_snapshots(snapshot_ids, destination_id):
    """Move captures through native folder membership and webhook handling."""
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder, Snapshot

    snapshots = Snapshot.objects.filter(pk__in=snapshot_ids)
    missing = set(snapshot_ids) - set(snapshots.values_list("pk", flat=True))
    if missing:
        raise click.ClickException(f"Snapshots not found: {', '.join(sorted(str(pk) for pk in missing))}")
    try:
        count = Folder.move_snapshots(snapshots, destination_id)
    except Folder.DoesNotExist as error:
        raise click.ClickException(f"Destination folder not found: {destination_id}") from error
    except ValidationError as error:
        raise click.ClickException(str(error)) from error
    write_record({"moved": count})
