#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import os
import sys
import shutil

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def install(dry_run: bool=False) -> None:
    """Detect and install ArchiveBox dependencies by running a dependency-check crawl"""

    from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.config.paths import ARCHIVE_DIR
    from archivebox.misc.logging import stderr
    from archivebox.cli.archivebox_init import init

    if not (os.access(ARCHIVE_DIR, os.R_OK) and ARCHIVE_DIR.is_dir()):
        init()  # must init full index because we need a db to store InstalledBinary entries in

    print('\n[green][+] Detecting ArchiveBox dependencies...[/green]')

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
    from crawls.models import Seed, Crawl
    from archivebox.base_models.models import get_or_create_system_user_pk

    # Create a seed and crawl for dependency detection
    # Using a minimal crawl that will trigger on_Crawl hooks
    created_by_id = get_or_create_system_user_pk()

    seed, _created = Seed.objects.get_or_create(
        uri='archivebox://install',
        label='Dependency detection',
        created_by_id=created_by_id,
        defaults={
            'extractor': 'auto',
        }
    )

    crawl, created = Crawl.objects.get_or_create(
        seed=seed,
        max_depth=0,
        created_by_id=created_by_id,
        defaults={
            'status': 'queued',
        }
    )

    # If crawl already existed, reset it to queued state so it can be processed again
    if not created:
        crawl.status = 'queued'
        crawl.retry_at = timezone.now()
        crawl.save()

    print(f'[+] Created dependency detection crawl: {crawl.id}')
    print(f'[+] Crawl status: {crawl.status}, retry_at: {crawl.retry_at}')

    # Verify the crawl is in the queue
    from crawls.models import Crawl as CrawlModel
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
    from workers.orchestrator import Orchestrator
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

    # Run version to show full status
    archivebox_path = shutil.which('archivebox') or sys.executable
    if 'python' in archivebox_path:
        os.system(f'{sys.executable} -m archivebox version')
    else:
        os.system(f'{archivebox_path} version')


@click.command()
@click.option('--dry-run', '-d', is_flag=True, help='Show what would happen without actually running', default=False)
@docstring(install.__doc__)
def main(**kwargs) -> None:
    install(**kwargs)
    

if __name__ == '__main__':
    main()
