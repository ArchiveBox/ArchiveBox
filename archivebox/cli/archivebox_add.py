#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox add'

import sys

from typing import TYPE_CHECKING

import rich_click as click

from django.utils import timezone
from django.db.models import QuerySet

from archivebox.misc.util import enforce_types, docstring
from archivebox import CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.config.permissions import USER, HOSTNAME
from archivebox.parsers import PARSERS


if TYPE_CHECKING:
    from core.models import Snapshot


ORCHESTRATOR = None

@enforce_types
def add(urls: str | list[str],
        depth: int | str=0,
        tag: str='',
        parser: str="auto",
        extract: str="",
        persona: str='Default',
        overwrite: bool=False,
        update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
        index_only: bool=False,
        bg: bool=False,
        created_by_id: int | None=None) -> QuerySet['Snapshot']:
    """Add a new URL or list of URLs to your archive"""

    global ORCHESTRATOR

    depth = int(depth)

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'
    
    # import models once django is set up
    from crawls.models import Seed, Crawl
    from workers.orchestrator import Orchestrator
    from archivebox.base_models.models import get_or_create_system_user_pk


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
        'EXTRACTORS': extract,
        'DEFAULT_PERSONA': persona or 'Default',
    })
    # 3. create a new Crawl pointing to the Seed
    crawl = Crawl.from_seed(seed, max_depth=depth)
    
    # 4. start the Orchestrator & wait until it completes
    #    ... orchestrator will create the root Snapshot, which creates pending ArchiveResults, which gets run by the ArchiveResultActors ...
    # from crawls.actors import CrawlActor
    # from core.actors import SnapshotActor, ArchiveResultActor

    if not bg:
        orchestrator = Orchestrator(exit_on_idle=True, max_concurrent_actors=4)
        orchestrator.start()
    
    # 5. return the list of new Snapshots created
    return crawl.snapshot_set.all()


@click.command()
@click.option('--depth', '-d', type=click.Choice(('0', '1')), default='0', help='Recursively archive linked pages up to N hops away')
@click.option('--tag', '-t', default='', help='Comma-separated list of tags to add to each snapshot e.g. tag1,tag2,tag3')
@click.option('--parser', type=click.Choice(['auto', *PARSERS.keys()]), default='auto', help='Parser for reading input URLs')
@click.option('--extract', '-e', default='', help='Comma-separated list of extractors to use e.g. title,favicon,screenshot,singlefile,...')
@click.option('--persona', default='Default', help='Authentication profile to use when archiving')
@click.option('--overwrite', '-F', is_flag=True, help='Overwrite existing data if URLs have been archived previously')
@click.option('--update', is_flag=True, default=ARCHIVING_CONFIG.ONLY_NEW, help='Retry any previously skipped/failed URLs when re-adding them')
@click.option('--index-only', is_flag=True, help='Just add the URLs to the index without archiving them now')
# @click.option('--update-all', is_flag=True, help='Update ALL links in index when finished adding new ones')
@click.option('--bg', is_flag=True, help='Run crawl in background worker instead of immediately')
@click.argument('urls', nargs=-1, type=click.Path())
@docstring(add.__doc__)
def main(**kwargs):
    """Add a new URL or list of URLs to your archive"""
    
    add(**kwargs)


if __name__ == '__main__':
    main()




# OLD VERSION:
# def add(urls: Union[str, List[str]],
#         tag: str='',
#         depth: int=0,
#         update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
#         update_all: bool=False,
#         index_only: bool=False,
#         overwrite: bool=False,
#         # duplicate: bool=False,  # TODO: reuse the logic from admin.py resnapshot to allow adding multiple snapshots by appending timestamp automatically
#         init: bool=False,
#         extractors: str="",
#         parser: str="auto",
#         created_by_id: int | None=None,
#         out_dir: Path=DATA_DIR) -> List[Link]:
#     """Add a new URL or list of URLs to your archive"""

#     from core.models import Snapshot, Tag
#     # from workers.supervisord_util import start_cli_workers, tail_worker_logs
#     # from workers.tasks import bg_archive_link
    

#     assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

#     extractors = extractors.split(",") if extractors else []

#     if init:
#         run_subcommand('init', stdin=None, pwd=out_dir)

#     # Load list of links from the existing index
#     check_data_folder()

#     # worker = start_cli_workers()
    
#     new_links: List[Link] = []
#     all_links = load_main_index(out_dir=out_dir)

#     log_importing_started(urls=urls, depth=depth, index_only=index_only)
#     if isinstance(urls, str):
#         # save verbatim stdin to sources
#         write_ahead_log = save_text_as_source(urls, filename='{ts}-import.txt', out_dir=out_dir)
#     elif isinstance(urls, list):
#         # save verbatim args to sources
#         write_ahead_log = save_text_as_source('\n'.join(urls), filename='{ts}-import.txt', out_dir=out_dir)
    

#     new_links += parse_links_from_source(write_ahead_log, root_url=None, parser=parser)

#     # If we're going one level deeper, download each link and look for more links
#     new_links_depth = []
#     if new_links and depth == 1:
#         log_crawl_started(new_links)
#         for new_link in new_links:
#             try:
#                 downloaded_file = save_file_as_source(new_link.url, filename=f'{new_link.timestamp}-crawl-{new_link.domain}.txt', out_dir=out_dir)
#                 new_links_depth += parse_links_from_source(downloaded_file, root_url=new_link.url)
#             except Exception as err:
#                 stderr('[!] Failed to get contents of URL {new_link.url}', err, color='red')

#     imported_links = list({link.url: link for link in (new_links + new_links_depth)}.values())
    
#     new_links = dedupe_links(all_links, imported_links)

#     write_main_index(links=new_links, out_dir=out_dir, created_by_id=created_by_id)
#     all_links = load_main_index(out_dir=out_dir)

#     tags = [
#         Tag.objects.get_or_create(name=name.strip(), defaults={'created_by_id': created_by_id})[0]
#         for name in tag.split(',')
#         if name.strip()
#     ]
#     if tags:
#         for link in imported_links:
#             snapshot = Snapshot.objects.get(url=link.url)
#             snapshot.tags.add(*tags)
#             snapshot.tags_str(nocache=True)
#             snapshot.save()
#         # print(f'    √ Tagged {len(imported_links)} Snapshots with {len(tags)} tags {tags_str}')

#     if index_only:
#         # mock archive all the links using the fake index_only extractor method in order to update their state
#         if overwrite:
#             archive_links(imported_links, overwrite=overwrite, methods=['index_only'], out_dir=out_dir, created_by_id=created_by_id)
#         else:
#             archive_links(new_links, overwrite=False, methods=['index_only'], out_dir=out_dir, created_by_id=created_by_id)
#     else:
#         # fully run the archive extractor methods for each link
#         archive_kwargs = {
#             "out_dir": out_dir,
#             "created_by_id": created_by_id,
#         }
#         if extractors:
#             archive_kwargs["methods"] = extractors

#         stderr()

#         ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

#         if update:
#             stderr(f'[*] [{ts}] Archiving + updating {len(imported_links)}/{len(all_links)}', len(imported_links), 'URLs from added set...', color='green')
#             archive_links(imported_links, overwrite=overwrite, **archive_kwargs)
#         elif update_all:
#             stderr(f'[*] [{ts}] Archiving + updating {len(all_links)}/{len(all_links)}', len(all_links), 'URLs from entire library...', color='green')
#             archive_links(all_links, overwrite=overwrite, **archive_kwargs)
#         elif overwrite:
#             stderr(f'[*] [{ts}] Archiving + overwriting {len(imported_links)}/{len(all_links)}', len(imported_links), 'URLs from added set...', color='green')
#             archive_links(imported_links, overwrite=True, **archive_kwargs)
#         elif new_links:
#             stderr(f'[*] [{ts}] Archiving {len(new_links)}/{len(all_links)} URLs from added set...', color='green')
#             archive_links(new_links, overwrite=False, **archive_kwargs)

#     # tail_worker_logs(worker['stdout_logfile'])

#     # if CAN_UPGRADE:
#     #     hint(f"There's a new version of ArchiveBox available! Your current version is {VERSION}. You can upgrade to {VERSIONS_AVAILABLE['recommended_version']['tag_name']} ({VERSIONS_AVAILABLE['recommended_version']['html_url']}). For more on how to upgrade: https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives\n")

#     return new_links

