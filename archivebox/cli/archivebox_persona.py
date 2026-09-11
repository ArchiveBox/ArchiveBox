#!/usr/bin/env python3

"""
archivebox persona <action> [args...] [--filters]

Manage Persona records (browser profiles for archiving).

Actions:
    create  - Create Personas
    list    - List Personas as JSONL (with optional filters)
    update  - Update Personas from stdin JSONL
    delete  - Delete Personas from stdin JSONL

Examples:
    # Create a new persona
    archivebox persona create work
    archivebox persona create --import=chrome personal
    archivebox persona create --import=edge work

    # List all personas
    archivebox persona list

    # Delete a persona
    archivebox persona list --name=old | archivebox persona delete --yes
"""

__package__ = "archivebox.cli"
__command__ = "archivebox persona"

import sys
import shutil
from pathlib import Path
from dataclasses import replace
from collections.abc import Iterable

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_util import apply_filters
from archivebox.personas import importers as persona_importers


# =============================================================================
# Validation Helpers
# =============================================================================


def validate_persona_name(name: str) -> tuple[bool, str]:
    """
    Validate persona name to prevent path traversal attacks.

    Returns:
        (is_valid, error_message): tuple indicating if name is valid
    """
    if not name or not name.strip():
        return False, "Persona name cannot be empty"

    # Check for path separators
    if "/" in name or "\\" in name:
        return False, "Persona name cannot contain path separators (/ or \\)"

    # Check for parent directory references
    if ".." in name:
        return False, "Persona name cannot contain parent directory references (..)"

    # Check for hidden files/directories
    if name.startswith("."):
        return False, "Persona name cannot start with a dot (.)"

    # Ensure name doesn't contain null bytes or other dangerous chars
    if "\x00" in name or "\n" in name or "\r" in name:
        return False, "Persona name contains invalid characters"

    return True, ""


def ensure_path_within_personas_dir(persona_path: Path) -> bool:
    """
    Verify that a persona path is within PERSONAS_DIR.

    This is a safety check to prevent path traversal attacks where
    a malicious persona name could cause operations on paths outside
    the expected PERSONAS_DIR.

    Returns:
        True if path is safe, False otherwise
    """
    from archivebox.config.constants import CONSTANTS

    try:
        # Resolve both paths to absolute paths
        personas_dir = CONSTANTS.PERSONAS_DIR.resolve()
        resolved_path = persona_path.resolve()

        # Check if resolved_path is a child of personas_dir
        return resolved_path.is_relative_to(personas_dir)
    except (ValueError, RuntimeError):
        return False


# =============================================================================
# CREATE
# =============================================================================


def create_personas(
    names: Iterable[str],
    import_from: str | None = None,
    profile: str | None = None,
    source: str | None = None,
    browser_binary: str | None = None,
) -> int:
    """
    Create Personas from names.

    If --import is specified, copy the browser profile to the persona directory
    and extract cookies.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.personas.models import Persona

    is_tty = sys.stdout.isatty()
    name_list = list(names) if names else []

    if not name_list:
        rprint("[yellow]No persona names provided. Pass names as arguments.[/yellow]", file=sys.stderr)
        return 1

    import_source = None
    if source and not import_from:
        rprint("[red]--source requires --import (the source browser name).[/red]", file=sys.stderr)
        return 1
    if import_from:
        try:
            if source:
                import_source = persona_importers.resolve_custom_import_source(source, profile_dir=profile)
                import_source = replace(import_source, browser=import_from.lower(), browser_binary=browser_binary)
            elif import_from.startswith(("http://", "https://", "ws://", "wss://")):
                import_source = persona_importers.resolve_custom_import_source(import_from)
            else:
                import_source = persona_importers.resolve_browser_import_source(import_from, profile_dir=profile)
            if browser_binary:
                import_source = replace(import_source, browser_binary=browser_binary)
        except ValueError as err:
            rprint(f"[red]{err}[/red]", file=sys.stderr)
            return 1

    created_count = 0
    for name in name_list:
        name = name.strip()
        if not name:
            continue

        # Validate persona name to prevent path traversal
        is_valid, error_msg = persona_importers.validate_persona_name(name)
        if not is_valid:
            rprint(f'[red]Invalid persona name "{name}": {error_msg}[/red]', file=sys.stderr)
            continue

        persona, created = Persona.objects.get_or_create(name=name)

        if created:
            persona.ensure_dirs()
            created_count += 1

        else:
            rprint(f"[dim]Persona already exists: {name}[/dim]", file=sys.stderr)

        cookies_file = Path(persona.path) / "cookies.txt"

        # Import browser profile if requested
        if import_source is not None:
            try:
                rprint(f"[dim]Importing {import_source.display_label}; copying settings and exporting cookies...[/dim]", file=sys.stderr)
                import_result = persona_importers.import_persona_from_source(
                    persona,
                    import_source,
                    copy_profile=True,
                    import_cookies=True,
                    capture_storage=False,
                )
            except (Exception, KeyboardInterrupt) as e:
                if created:
                    shutil.rmtree(persona.path, ignore_errors=True)
                    persona.delete()
                rprint(f"[red]Failed to import browser profile: {e}[/red]", file=sys.stderr)
                return 1

            if import_result.profile_copied:
                rprint("[green]Copied browser profile to persona[/green]", file=sys.stderr)
            if import_result.cookies_imported:
                rprint(f"[green]Extracted {import_result.cookie_count} cookies to {cookies_file}[/green]", file=sys.stderr)
            elif not import_result.profile_copied:
                rprint("[yellow]Could not import cookies automatically.[/yellow]", file=sys.stderr)

            for warning in import_result.warnings:
                rprint(f"[yellow]{warning}[/yellow]", file=sys.stderr)

        if created:
            rprint(f"[green]Created persona: {name}[/green]", file=sys.stderr)
        if not is_tty:
            write_record(
                {
                    "id": str(persona.id),
                    "name": persona.name,
                    "path": str(persona.path),
                    "CHROME_USER_DATA_DIR": persona.CHROME_USER_DATA_DIR,
                    "COOKIES_FILE": persona.COOKIES_FILE,
                },
            )

    rprint(f"[green]Created {created_count} new persona(s)[/green]", file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================


def list_personas(
    name: str | None = None,
    name__icontains: str | None = None,
    limit: int | None = None,
) -> int:
    """
    List Personas as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.personas.models import Persona

    is_tty = sys.stdout.isatty()

    queryset = Persona.objects.all().order_by("name")

    # Apply filters
    filter_kwargs = {
        "name": name,
        "name__icontains": name__icontains,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for persona in queryset:
        cookies_status = "[green]✓[/green]" if persona.COOKIES_FILE else "[dim]✗[/dim]"
        chrome_status = "[green]✓[/green]" if Path(persona.CHROME_USER_DATA_DIR).exists() else "[dim]✗[/dim]"

        if is_tty:
            rprint(f"[cyan]{persona.name:20}[/cyan] cookies:{cookies_status} chrome:{chrome_status} [dim]{persona.path}[/dim]")
        else:
            write_record(
                {
                    "id": str(persona.id),
                    "name": persona.name,
                    "path": str(persona.path),
                    "CHROME_USER_DATA_DIR": persona.CHROME_USER_DATA_DIR,
                    "COOKIES_FILE": persona.COOKIES_FILE,
                },
            )
        count += 1

    rprint(f"[dim]Listed {count} persona(s)[/dim]", file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================


def update_personas(name: str | None = None) -> int:
    """
    Update Personas from stdin JSONL.

    Reads Persona records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.personas.models import Persona

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        persona_id = record.get("id")
        old_name = record.get("name")

        if not persona_id and not old_name:
            continue

        try:
            if persona_id:
                persona = Persona.objects.get(id=persona_id)
            else:
                persona = Persona.objects.get(name=old_name)

            # Apply updates from CLI flags
            if name:
                # Validate new name to prevent path traversal
                is_valid, error_msg = persona_importers.validate_persona_name(name)
                if not is_valid:
                    rprint(f'[red]Invalid new persona name "{name}": {error_msg}[/red]', file=sys.stderr)
                    continue

                # Rename the persona directory too
                old_path = persona.path
                persona.name = name
                new_path = persona.path

                if old_path.exists() and old_path != new_path:
                    shutil.move(str(old_path), str(new_path))

                persona.save()

            updated_count += 1

            if not is_tty:
                write_record(
                    {
                        "id": str(persona.id),
                        "name": persona.name,
                        "path": str(persona.path),
                    },
                )

        except Persona.DoesNotExist:
            rprint(f"[yellow]Persona not found: {persona_id or old_name}[/yellow]", file=sys.stderr)
            continue

    rprint(f"[green]Updated {updated_count} persona(s)[/green]", file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================


def delete_personas(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Personas from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.personas.models import Persona

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    # Collect persona IDs or names
    persona_ids = []
    persona_names = []
    for r in records:
        if r.get("id"):
            persona_ids.append(r["id"])
        elif r.get("name"):
            persona_names.append(r["name"])

    if not persona_ids and not persona_names:
        rprint("[yellow]No valid persona IDs or names in input[/yellow]", file=sys.stderr)
        return 1

    from django.db.models import Q

    query = Q()
    if persona_ids:
        query |= Q(id__in=persona_ids)
    if persona_names:
        query |= Q(name__in=persona_names)

    personas = Persona.objects.filter(query)
    count = personas.count()

    if count == 0:
        rprint("[yellow]No matching personas found[/yellow]", file=sys.stderr)
        return 0

    if dry_run:
        rprint(f"[yellow]Would delete {count} persona(s) (dry run)[/yellow]", file=sys.stderr)
        for persona in personas:
            rprint(f"  {persona.name} ({persona.path})", file=sys.stderr)
        return 0

    if not yes:
        rprint("[red]Use --yes to confirm deletion[/red]", file=sys.stderr)
        return 1

    # Delete persona directories and database records
    deleted_count = 0
    for persona in personas:
        persona_path = persona.path

        # Safety check: ensure path is within PERSONAS_DIR before deletion
        if not ensure_path_within_personas_dir(persona_path):
            rprint(f'[red]Security error: persona path "{persona_path}" is outside PERSONAS_DIR. Skipping deletion.[/red]', file=sys.stderr)
            continue

        if persona_path.exists():
            shutil.rmtree(persona_path)
        persona.delete()
        deleted_count += 1

    rprint(f"[green]Deleted {deleted_count} persona(s)[/green]", file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Persona records (browser profiles)."""
    pass


@main.command("create")
@click.argument("names", nargs=-1)
@click.option("--import", "import_from", help="Import from chrome, chromium, brave, edge, or a live CDP URL")
@click.option("--source", help="Source browser user-data directory or exact profile path (including Docker mounts)")
@click.option(
    "--browser-binary",
    type=click.Path(exists=True, dir_okay=False),
    help="Source Chromium browser executable; required for other Chromium-based browsers",
)
@click.option("--profile", help="Profile directory name under the user data dir (e.g. Default, Profile 1)")
def create_cmd(names: tuple, import_from: str | None, profile: str | None, source: str | None, browser_binary: str | None):
    """Create Personas, optionally importing from a browser profile."""
    sys.exit(create_personas(names, import_from=import_from, profile=profile, source=source, browser_binary=browser_binary))


@main.command("list")
@click.option("--name", help="Filter by exact name")
@click.option("--name__icontains", help="Filter by name contains")
@click.option("--limit", "-n", type=int, help="Limit number of results")
def list_cmd(name: str | None, name__icontains: str | None, limit: int | None):
    """List Personas as JSONL."""
    sys.exit(list_personas(name=name, name__icontains=name__icontains, limit=limit))


@main.command("update")
@click.option("--name", "-n", help="Set new name")
def update_cmd(name: str | None):
    """Update Personas from stdin JSONL."""
    sys.exit(update_personas(name=name))


@main.command("delete")
@click.option("--yes", "-y", is_flag=True, help="Confirm deletion")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Personas from stdin JSONL."""
    sys.exit(delete_personas(yes=yes, dry_run=dry_run))


if __name__ == "__main__":
    main()
