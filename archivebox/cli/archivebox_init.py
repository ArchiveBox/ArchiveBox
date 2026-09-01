#!/usr/bin/env python3

__package__ = "archivebox.cli"

import os
import sys
from pathlib import Path

from rich import print
import rich_click as click

from archivebox.misc.util import docstring, enforce_types


def _display_data_path(path: Path, data_dir: Path) -> str:
    path = Path(path).resolve()
    data_dir = Path(data_dir).resolve()
    try:
        return f"./{path.relative_to(data_dir)}"
    except ValueError:
        return str(path)


@enforce_types
def init(force: bool = False, quick: bool = False, install: bool = False) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""

    from archivebox.misc.checks import check_not_inside_source_dir

    check_not_inside_source_dir()

    from archivebox.config import CONSTANTS, VERSION
    from archivebox.config.common import get_config
    from archivebox.config.collection import write_config_file
    from archivebox.misc.db import apply_migrations, database_exists, ensure_database_ready
    from archivebox.misc.checks import check_migrations

    config = get_config()

    is_empty = not len(set(os.listdir(CONSTANTS.DATA_DIR)) - CONSTANTS.ALLOWED_IN_DATA_DIR)
    existing_index = database_exists()
    if is_empty and not existing_index:
        print(f"[turquoise4][+] Initializing a new ArchiveBox v{VERSION} collection...[/turquoise4]")
        print("[green]----------------------------------------------------------------------[/green]")
    elif existing_index:
        # TODO: properly detect and print the existing version in current index as well
        print(f"[green][*] Verifying and updating existing ArchiveBox collection to v{VERSION}...[/green]")
        print("[green]----------------------------------------------------------------------[/green]")
    else:
        if force:
            print("[red][!] This folder appears to already have files in it, but no index.sqlite3 is present.[/red]")
            print("[red]    Because --force was passed, ArchiveBox will initialize anyway (which may overwrite existing files).[/red]")
        else:
            print(
                "[red][X] This folder appears to already have files in it, but no index.sqlite3 present.[/red]\n\n"
                "    You must run init in a completely empty directory, or an existing data folder.\n\n"
                "    [violet]Hint:[/violet] To import an existing data folder make sure to cd into the folder first, \n"
                "    then run and run 'archivebox init' to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)",
            )
            raise SystemExit(2)

    if existing_index:
        print("\n[green][*] Verifying archive folder structure...[/green]")
    else:
        print("\n[green][+] Building archive folder structure...[/green]")

    archive_path = _display_data_path(CONSTANTS.ARCHIVE_DIR, CONSTANTS.DATA_DIR)
    sources_path = _display_data_path(CONSTANTS.SOURCES_DIR, CONSTANTS.DATA_DIR)
    logs_path = _display_data_path(CONSTANTS.LOGS_DIR, CONSTANTS.DATA_DIR)
    print(f"    + {archive_path}, {sources_path}, {logs_path}...")
    Path(CONSTANTS.SOURCES_DIR).mkdir(exist_ok=True)
    CONSTANTS.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.USERS_DIR.mkdir(parents=True, exist_ok=True)
    Path(CONSTANTS.LOGS_DIR).mkdir(exist_ok=True)
    for path in (Path(CONSTANTS.SOURCES_DIR), CONSTANTS.ARCHIVE_DIR, CONSTANTS.USERS_DIR, Path(CONSTANTS.LOGS_DIR)):
        path.chmod(int(config.OUTPUT_PERMISSIONS, base=8) | 0o111)

    print(f"    + {_display_data_path(CONSTANTS.CONFIG_FILE, CONSTANTS.DATA_DIR)}...")

    # create the .archivebox_id file with a unique ID for this collection
    from archivebox.config.paths import _get_collection_id

    _get_collection_id(CONSTANTS.DATA_DIR, force_create=True)

    # create the ArchiveBox.conf file
    write_config_file({"SECRET_KEY": config.SECRET_KEY})

    if existing_index:
        print("\n[green][*] Verifying main SQL index and running any migrations needed...[/green]")
    else:
        print("\n[green][+] Building main SQL index and running initial migrations...[/green]")

    # For postgres, make sure the server is reachable and create the database
    # if it doesn't exist yet (sqlite creates its file automatically).
    ensure_database_ready()

    from archivebox.config.django import setup_django

    setup_django()
    previous_wants_init = os.environ.get("ARCHIVEBOX_WANTS_INIT")
    os.environ["ARCHIVEBOX_WANTS_INIT"] = "1"
    try:
        check_migrations(blocking=True, auto_apply=False)

        for migration_line in apply_migrations(CONSTANTS.DATA_DIR):
            sys.stdout.write(f"    {migration_line}\n")
    finally:
        if previous_wants_init is None:
            os.environ.pop("ARCHIVEBOX_WANTS_INIT", None)
        else:
            os.environ["ARCHIVEBOX_WANTS_INIT"] = previous_wants_init

    from archivebox.misc.db import database_display_location, is_postgres

    assert database_exists()
    print()
    if is_postgres():
        print(f"    √ {database_display_location()}")
    else:
        print(f"    √ {_display_data_path(CONSTANTS.DATABASE_FILE, CONSTANTS.DATA_DIR)}")

    print()
    print("[dodger_blue3][*] Checking links from indexes and archive folders (safe to Ctrl+C)...[/dodger_blue3]")

    from archivebox.core.models import Snapshot

    snapshot_count = 0

    if existing_index:
        snapshot_count = Snapshot.objects.count()
        print(f"    √ Loaded {snapshot_count} links from existing main index.")

    print("    > Skipping orphan snapshot import during init.")
    print()
    print("    [violet]Hint:[/violet] To import orphaned snapshot directories and reconcile filesystem state, run:")
    print("        archivebox update")

    print("\n[green]----------------------------------------------------------------------[/green]")

    from django.contrib.auth.models import User

    config = get_config()
    if (config.ADMIN_USERNAME and config.ADMIN_PASSWORD) and not User.objects.filter(
        username=config.ADMIN_USERNAME,
    ).exists():
        print("[green][+] Found ADMIN_USERNAME and ADMIN_PASSWORD configuration options, creating new admin user.[/green]")
        User.objects.create_superuser(username=config.ADMIN_USERNAME, password=config.ADMIN_PASSWORD)

    if existing_index:
        print("[green][√] Done. Verified and updated the existing ArchiveBox collection.[/green]")
    else:
        print(f"[green][√] Done. A new ArchiveBox collection was initialized ({snapshot_count} links).[/green]")

    CONSTANTS.PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.DEFAULT_TMP_DIR.mkdir(parents=True, exist_ok=True)

    from archivebox.config.paths import create_and_chown_dir, get_or_create_working_tmp_dir, get_or_create_working_lib_dir

    config = get_config()
    create_and_chown_dir(config.TMP_DIR)
    create_and_chown_dir(config.ABXPKG_LIB_DIR)
    create_and_chown_dir(config.ABXPKG_LIB_DIR / "bin")

    working_tmp_dir = get_or_create_working_tmp_dir(autofix=True, quiet=True)
    if working_tmp_dir:
        working_tmp_dir.mkdir(parents=True, exist_ok=True)

    working_lib_dir = get_or_create_working_lib_dir(autofix=True, quiet=True)
    if working_lib_dir:
        working_lib_dir.mkdir(parents=True, exist_ok=True)

    if install:
        from archivebox.cli.archivebox_install import install as install_method

        install_method()

    if Snapshot.objects.count() < 25:  # hide the hints for experienced users
        from archivebox.core.routes_util import build_admin_url

        admin_url = build_admin_url("/admin/", config=config)
        print()
        print("    [violet]Hint:[/violet] To finish web setup, run:")
        print(
            f"        archivebox server  # then visit [deep_sky_blue4][link={admin_url}]{admin_url}[/link][/deep_sky_blue4]",
        )
        print()
        print("    To add new links, you can run:")
        print("        archivebox add < ~/some/path/to/list_of_links.txt")
        print()
        print("    For more usage and examples, run:")
        print("        archivebox help")


@click.command()
@click.option("--force", "-f", is_flag=True, help="Ignore unrecognized files in current directory and initialize anyway")
@click.option("--quick", "-q", is_flag=True, help="Run any updates or migrations without rechecking all snapshot dirs")
@click.option("--install", "--setup", "-s", is_flag=True, help="Automatically install dependencies and extras used for archiving")
@docstring(init.__doc__)
def main(**kwargs) -> None:
    init(**kwargs)


if __name__ == "__main__":
    main()
