#!/usr/bin/env python3

__package__ = "archivebox.cli"

import os

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def install(binaries: tuple[str, ...] = (), binproviders: str = "*", dry_run: bool = False) -> None:
    """Detect and install ArchiveBox dependencies by running the abx-dl install flow

    Examples:
        archivebox install                              # Install all dependencies
        archivebox install wget curl                    # Install only wget and curl
        archivebox install --binproviders=pip yt-dlp    # Install yt-dlp using only pip
        archivebox install --binproviders=brew,apt      # Install all deps using only brew or apt
    """

    from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.config.paths import ARCHIVE_DIR
    from archivebox.misc.logging import stderr
    from archivebox.cli.archivebox_init import init

    if not (os.access(ARCHIVE_DIR, os.R_OK) and ARCHIVE_DIR.is_dir()):
        init()  # must init full index because we need a db to store Binary entries in

    # Show what we're installing
    if binaries:
        print(f"\n[green][+] Installing specific binaries: {', '.join(binaries)}[/green]")
    else:
        print("\n[green][+] Detecting and installing all ArchiveBox dependencies...[/green]")

    if binproviders != "*":
        print(f"[green][+] Using providers: {binproviders}[/green]")

    if IS_ROOT:
        EUID = os.geteuid()
        print()
        print(f"[yellow]:warning:  Running as UID=[blue]{EUID}[/blue].[/yellow]")
        print(f"    DATA_DIR will be owned by [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue].")
        print()

    if dry_run:
        print("[dim]Dry run - would run the abx-dl install flow[/dim]")
        return

    # Set up Django
    from archivebox.config.django import setup_django

    setup_django()

    plugin_names = list(binaries)
    if binproviders != "*":
        plugin_names.extend(provider.strip() for provider in binproviders.split(",") if provider.strip())

    print("[+] Running installer via abx-dl bus...")
    print()

    from archivebox.services.runner import run_install

    run_install(plugin_names=plugin_names or None)

    print()

    # Check for superuser
    from django.contrib.auth import get_user_model

    User = get_user_model()

    if not User.objects.filter(is_superuser=True).exclude(username="system").exists():
        stderr("\n[+] Don't forget to create a new admin user for the Web UI...", color="green")
        stderr("    archivebox manage createsuperuser")

    print()

    # Show version to display full status including installed binaries
    # Django is already loaded, so just import and call the function directly
    from archivebox.cli.archivebox_version import version as show_version

    show_version(quiet=False)


@click.command()
@click.argument("binaries", nargs=-1, type=str, required=False)
@click.option(
    "--binproviders",
    "-p",
    default="*",
    help="Comma-separated list of providers to use (pip,npm,brew,apt,env,custom) or * for all",
    show_default=True,
)
@click.option("--dry-run", "-d", is_flag=True, help="Show what would happen without actually running", default=False)
@docstring(install.__doc__)
def main(**kwargs) -> None:
    install(**kwargs)


if __name__ == "__main__":
    main()
