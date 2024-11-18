#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys
import argparse

from typing import IO, TYPE_CHECKING


from django.utils import timezone
from django.db.models import QuerySet


from archivebox import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.config.django import setup_django
from archivebox.config.permissions import USER, HOSTNAME
from archivebox.misc.checks import check_data_folder
from archivebox.parsers import PARSERS
from archivebox.logging_util import SmartFormatter, accept_stdin, stderr

from abid_utils.models import get_or_create_system_user_pk

if TYPE_CHECKING:
    from core.models import Snapshot


ORCHESTRATOR = None


def add(urls: str | list[str],
        tag: str='',
        depth: int=0,
        update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
        update_all: bool=False,
        index_only: bool=False,
        overwrite: bool=False,
        extractors: str="",
        parser: str="auto",
        persona: str='Default',
        created_by_id: int | None=None) -> QuerySet['Snapshot']:
    """Add a new URL or list of URLs to your archive"""

    global ORCHESTRATOR

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

    # 0. setup abx, django, check_data_folder
    setup_django()
    check_data_folder()
    
    
    from seeds.models import Seed
    from crawls.models import Crawl
    from actors.orchestrator import Orchestrator

    
    created_by_id = created_by_id or get_or_create_system_user_pk()
    
    # 1. save the provided urls to sources/2024-11-05__23-59-59__cli_add.txt
    sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__cli_add.txt'
    sources_file.write_text(urls if isinstance(urls, str) else '\n'.join(urls))
    
    # 2. create a new Seed pointing to the sources/2024-11-05__23-59-59__cli_add.txt
    cli_args = [*sys.argv]
    if cli_args[0].lower().endswith('archivebox'):
        cli_args[0] = 'archivebox'  # full path to archivebox bin to just archivebox e.g. /Volumes/NVME/Users/squash/archivebox/.venv/bin/archivebox -> archivebox
    cmd_str = ' '.join(cli_args)
    seed = Seed.from_file(sources_file, label=f'{USER}@{HOSTNAME} $ {cmd_str}', parser=parser, tag=tag, created_by=created_by_id, config={
        'ONLY_NEW': not update,
        'INDEX_ONLY': index_only,
        'OVERWRITE': overwrite,
        'EXTRACTORS': extractors,
        'DEFAULT_PERSONA': persona or 'Default',
    })
    # 3. create a new Crawl pointing to the Seed
    crawl = Crawl.from_seed(seed, max_depth=depth)
    
    # 4. start the Orchestrator & wait until it completes
    #    ... orchestrator will create the root Snapshot, which creates pending ArchiveResults, which gets run by the ArchiveResultActors ...
    # from crawls.actors import CrawlActor
    # from core.actors import SnapshotActor, ArchiveResultActor

    orchestrator = Orchestrator(exit_on_idle=True, max_concurrent_actors=2)
    orchestrator.start()
    
    # 5. return the list of new Snapshots created
    return crawl.snapshot_set.all()


def main(args: list[str] | None=None, stdin: IO | None=None, pwd: str | None=None) -> None:
    """Add a new URL or list of URLs to your archive"""
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=add.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--tag', '-t',
        type=str,
        default='',
        help="Tag the added URLs with the provided tags e.g. --tag=tag1,tag2,tag3",
    )
    parser.add_argument(
        '--update', #'-u',
        action='store_true',
        default=not ARCHIVING_CONFIG.ONLY_NEW,  # when ONLY_NEW=True we skip updating old links
        help="Also retry previously skipped/failed links when adding new links",
    )
    parser.add_argument(
        '--update-all', #'-n',
        action='store_true',
        default=False, 
        help="Also update ALL links in index when finished adding new links",
    )
    parser.add_argument(
        '--index-only', #'-o',
        action='store_true',
        help="Add the links to the main index without archiving them",
    )
    parser.add_argument(
        'urls',
        nargs='*',
        type=str,
        default=None,
        help=(
            'URLs or paths to archive e.g.:\n'
            '    https://getpocket.com/users/USERNAME/feed/all\n'
            '    https://example.com/some/rss/feed.xml\n'
            '    https://example.com\n'
            '    ~/Downloads/firefox_bookmarks_export.html\n'
            '    ~/Desktop/sites_list.csv\n'
        )
    )
    parser.add_argument(
        "--depth",
        action="store",
        default=0,
        choices=[0, 1],
        type=int,
        help="Recursively archive all linked pages up to this many hops away"
    )
    parser.add_argument(
        "--overwrite",
        default=False,
        action="store_true",
        help="Re-archive URLs from scratch, overwriting any existing files"
    )
    parser.add_argument(
        "--extract", '-e',
        type=str,
        help="Pass a list of the extractors to be used. If the method name is not correct, it will be ignored. \
              This does not take precedence over the configuration",
        default=""
    )
    parser.add_argument(
        "--parser",
        type=str,
        help="Parser used to read inputted URLs.",
        default="auto",
        choices=["auto", *PARSERS.keys()],
    )
    parser.add_argument(
        "--persona",
        type=str,
        help="Name of accounts persona to use when archiving.",
        default="Default",
    )
    command = parser.parse_args(args or ())
    urls = command.urls

    stdin_urls = ''
    if not urls:
        stdin_urls = accept_stdin(stdin)

    if (stdin_urls and urls) or (not stdin and not urls):
        stderr(
            '[X] You must pass URLs/paths to add via stdin or CLI arguments.\n',
            color='red',
        )
        raise SystemExit(2)
    add(
        urls=stdin_urls or urls,
        depth=command.depth,
        tag=command.tag,
        update=command.update,
        update_all=command.update_all,
        index_only=command.index_only,
        overwrite=command.overwrite,
        extractors=command.extract,
        parser=command.parser,
        persona=command.persona,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
