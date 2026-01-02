#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import os
import sys
import shutil

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def install(binaries: tuple[str, ...] = (), binproviders: str = '*', dry_run: bool = False) -> None:
    """Detect and install ArchiveBox dependencies by running a dependency-check crawl

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
        print(f'\n[green][+] Installing specific binaries: {", ".join(binaries)}[/green]')
    else:
        print('\n[green][+] Detecting and installing all ArchiveBox dependencies...[/green]')

    if binproviders != '*':
        print(f'[green][+] Using providers: {binproviders}[/green]')

    if IS_ROOT:
        EUID = os.geteuid()
        print()
        print(f'[yellow]:warning:  Running as UID=[blue]{EUID}[/blue].[/yellow]')
        print(f'    DATA_DIR will be owned by [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue].')
        print()

    if dry_run:
        print('[dim]Dry run - would create a crawl to detect dependencies[/dim]')
        return

    # Set up Django
    from archivebox.config.django import setup_django
    setup_django()

    from django.utils import timezone
    from archivebox.crawls.models import Crawl
    from archivebox.base_models.models import get_or_create_system_user_pk

    # Create a crawl for dependency detection
    # Using a minimal crawl that will trigger on_Crawl hooks
    created_by_id = get_or_create_system_user_pk()

    # Build config for this crawl using existing PLUGINS filter
    crawl_config = {}

    # Combine binary names and provider names into PLUGINS list
    plugins = []
    if binaries:
        plugins.extend(binaries)
    if binproviders != '*':
        plugins.extend(binproviders.split(','))

    if plugins:
        crawl_config['PLUGINS'] = ','.join(plugins)

    crawl, created = Crawl.objects.get_or_create(
        urls='archivebox://install',
        defaults={
            'label': 'Dependency detection',
            'created_by_id': created_by_id,
            'max_depth': 0,
            'status': 'queued',
            'config': crawl_config,
        }
    )

    # If crawl already existed, reset it to queued state so it can be processed again
    if not created:
        crawl.status = 'queued'
        crawl.retry_at = timezone.now()
        crawl.config = crawl_config  # Update config
        crawl.save()

    print(f'[+] Created dependency detection crawl: {crawl.id}')
    if crawl_config:
        print(f'[+] Crawl config: {crawl_config}')
    print(f'[+] Crawl status: {crawl.status}, retry_at: {crawl.retry_at}')

    # Verify the crawl is in the queue
    from archivebox.crawls.models import Crawl as CrawlModel
    queued_crawls = CrawlModel.objects.filter(
        retry_at__lte=timezone.now()
    ).exclude(
        status__in=CrawlModel.FINAL_STATES
    )
    print(f'[+] Crawls in queue: {queued_crawls.count()}')
    if queued_crawls.exists():
        for c in queued_crawls:
            print(f'    - Crawl {c.id}: status={c.status}, retry_at={c.retry_at}')

    print('[+] Running crawl to detect binaries via on_Crawl hooks...')
    print()

    # Run the crawl synchronously (this triggers on_Crawl hooks)
    from archivebox.workers.orchestrator import Orchestrator
    orchestrator = Orchestrator(exit_on_idle=True)
    orchestrator.runloop()

    print()

    # Check for superuser
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not User.objects.filter(is_superuser=True).exclude(username='system').exists():
        stderr('\n[+] Don\'t forget to create a new admin user for the Web UI...', color='green')
        stderr('    archivebox manage createsuperuser')

    print()

    # Show version to display full status including installed binaries
    # Django is already loaded, so just import and call the function directly
    from archivebox.cli.archivebox_version import version as show_version
    show_version(quiet=False)


@click.command()
@click.argument('binaries', nargs=-1, type=str, required=False)
@click.option('--binproviders', '-p', default='*', help='Comma-separated list of providers to use (pip,npm,brew,apt,env,custom) or * for all', show_default=True)
@click.option('--dry-run', '-d', is_flag=True, help='Show what would happen without actually running', default=False)
@docstring(install.__doc__)
def main(**kwargs) -> None:
    install(**kwargs)
    

if __name__ == '__main__':
    main()
