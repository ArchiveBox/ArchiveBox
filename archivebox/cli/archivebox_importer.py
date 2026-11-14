"""Configure importers, queue actions, and inspect durable run history."""

import json
from dataclasses import asdict

import rich_click as click

from archivebox.misc.jsonl import write_record, write_record_table


@click.group()
def main():
    """Manage importer sources and runs."""


@main.command("catalog")
def catalog():
    """List installed importers and their settings schemas."""
    from archivebox.importers.catalog import get_importers

    write_record_table(asdict(item) for item in get_importers().values())


@main.command("list")
@click.option("--format", type=click.Choice(["jsonl", "json", "csv", "tsv"]), default="jsonl")
def list_sources(format):
    """List sources with persona IDs, names, settings and schedules."""
    from archivebox.importers.models import ImporterSource

    write_record_table(
        (source.to_json() for source in ImporterSource.objects.select_related("created_by", "persona", "folder")),
        format=format,
    )


@main.command("get")
@click.argument("source_id", type=click.UUID)
def get_source(source_id):
    """Read a configured importer."""
    from archivebox.importers.models import ImporterSource

    write_record(ImporterSource.objects.get(pk=source_id).to_json())


@main.command("create")
@click.option("--plugin", required=True)
@click.option("--feed", required=True)
@click.option("--name", default="")
@click.option("--settings", default="{}", help="JSON plugin settings; see importer catalog.")
@click.option("--persona-id", type=click.UUID)
@click.option("--folder-id", type=click.UUID)
@click.option("--schedule", default="")
@click.option("--tags", default="")
@click.option("--limit", type=click.IntRange(1, 500), default=100)
def create_source(plugin, feed, name, settings, persona_id, folder_id, schedule, tags, limit):
    """Create a source with the same validation as the importer UI."""
    from django.core.exceptions import ValidationError
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import save_source

    try:
        settings = json.loads(settings)
        if not isinstance(settings, dict):
            raise ValueError("Settings must be a JSON object.")
        source = save_source(
            ImporterSource(created_by_id=get_or_create_system_user_pk()),
            dict(
                plugin=plugin,
                feed=feed,
                name=name,
                settings=settings,
                persona_id=persona_id,
                folder_id=folder_id,
                schedule=schedule,
                tags=tags,
                limit=limit,
            ),
        )
    except (ValidationError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    write_record(source.to_json())


@main.command("update")
@click.argument("source_id", type=click.UUID)
@click.option("--data", required=True, help="JSON fields: name, settings, persona_id, folder_id, schedule, tags, limit, enabled.")
def update_source(source_id, data):
    """Edit an idle source; committed progress protects its account and settings."""
    from django.core.exceptions import ValidationError
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import save_source

    try:
        values = json.loads(data)
        if not isinstance(values, dict) or set(values) - {
            "name",
            "settings",
            "persona_id",
            "folder_id",
            "schedule",
            "tags",
            "limit",
            "enabled",
        }:
            raise ValueError("Unknown importer fields.")
        source = save_source(ImporterSource.objects.get(pk=source_id), values)
    except (ValidationError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    write_record(source.to_json())


@main.command("delete")
@click.argument("source_id", type=click.UUID)
@click.option("--yes", is_flag=True, required=True)
def delete_source(source_id, yes):
    """Delete an idle source and its run history; existing captures are preserved."""
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import delete_source as remove_source

    try:
        remove_source(ImporterSource.objects.get(pk=source_id))
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    write_record({"deleted": True, "id": source_id.hex})


@main.command("action")
@click.argument("source_id", type=click.UUID)
@click.argument("operation", type=click.Choice(["check", "preview", "import", "pause", "resume", "reset", "reset_code"]))
def source_action(source_id, operation):
    """Queue a worker action, pause/resume scheduling, or reset progress."""
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import source_action as execute

    try:
        result = execute(ImporterSource.objects.get(pk=source_id), operation)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    write_record(result.to_json())


@main.command("runs")
@click.option("--source-id", type=click.UUID)
@click.option("--limit", type=click.IntRange(1, 1000), default=100)
@click.option("--offset", type=click.IntRange(min=0), default=0)
@click.option("--format", type=click.Choice(["jsonl", "json", "csv", "tsv"]), default="jsonl")
def list_runs(source_id, limit, offset, format):
    """List run history including source, process and crawl IDs."""
    from archivebox.importers.models import ImporterRun

    runs = ImporterRun.objects.select_related("source")
    if source_id:
        runs = runs.filter(source_id=source_id)
    write_record_table((run.to_json() for run in runs[offset : offset + limit]), format=format)


@main.command("run")
@click.argument("run_id", type=click.UUID)
def get_run(run_id):
    """Read one run's state, discovered links and result."""
    from archivebox.importers.models import ImporterRun

    write_record(ImporterRun.objects.get(pk=run_id).to_json())
