#!/usr/bin/env python3

__package__ = 'archivebox.cli'


import rich_click as click

from typing import Iterable

from archivebox.misc.util import enforce_types, docstring
from archivebox.index import (
    LINK_FILTERS,
    get_indexed_folders,
    get_archived_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_invalid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
)


@enforce_types
def update(filter_patterns: Iterable[str]=(),
          only_new: bool=False,
          index_only: bool=False,
          resume: float | None=None,
          overwrite: bool=False,
          before: float | None=None,
          after: float | None=None,
          status: str='indexed',
          filter_type: str='exact',
          extract: str="") -> None:
    """Import any new links from subscriptions and retry any previously failed/skipped links"""
    
    from archivebox.config.django import setup_django
    setup_django()
    
    from workers.orchestrator import Orchestrator
    orchestrator = Orchestrator(exit_on_idle=False)
    orchestrator.start()


@click.command()
@click.option('--only-new', is_flag=True, help="Don't attempt to retry previously skipped/failed links when updating")
@click.option('--index-only', is_flag=True, help="Update the main index without archiving any content")
@click.option('--resume', type=float, help='Resume the update process from a given timestamp')
@click.option('--overwrite', '-F', is_flag=True, help='Ignore existing archived content and overwrite with new versions (DANGEROUS)')
@click.option('--before', type=float, help="Update only links bookmarked before the given timestamp")
@click.option('--after', type=float, help="Update only links bookmarked after the given timestamp") 
@click.option('--status', type=click.Choice([
    'indexed', 'archived', 'unarchived',
    'present', 'valid', 'invalid',
    'duplicate', 'orphaned', 'corrupted', 'unrecognized'
]), default='indexed', help=f'''
Update only links or data directories that have the given status:
    indexed       {get_indexed_folders.__doc__} (the default)
    archived      {get_archived_folders.__doc__}
    unarchived    {get_unarchived_folders.__doc__}

    present       {get_present_folders.__doc__}
    valid         {get_valid_folders.__doc__}
    invalid       {get_invalid_folders.__doc__}

    duplicate     {get_duplicate_folders.__doc__}
    orphaned      {get_orphaned_folders.__doc__}
    corrupted     {get_corrupted_folders.__doc__}
    unrecognized  {get_unrecognized_folders.__doc__}
''')
@click.option('--filter-type', '-t', type=click.Choice([*LINK_FILTERS.keys(), 'search']), default='exact', help='Type of pattern matching to use when filtering URLs')
@click.option('--extract', '-e', default='', help='Comma-separated list of extractors to use e.g. title,favicon,screenshot,singlefile,...')
@click.argument('filter_patterns', nargs=-1)
@docstring(update.__doc__)
def main(**kwargs):
    """Import any new links from subscriptions and retry any previously failed/skipped links"""
    update(**kwargs)


if __name__ == '__main__':
    main()




# LEGACY VERSION:
# @enforce_types
# def update(resume: Optional[float]=None,
#            only_new: bool=ARCHIVING_CONFIG.ONLY_NEW,
#            index_only: bool=False,
#            overwrite: bool=False,
#            filter_patterns_str: Optional[str]=None,
#            filter_patterns: Optional[List[str]]=None,
#            filter_type: Optional[str]=None,
#            status: Optional[str]=None,
#            after: Optional[str]=None,
#            before: Optional[str]=None,
#            extractors: str="",
#            out_dir: Path=DATA_DIR) -> List[Link]:
#     """Import any new links from subscriptions and retry any previously failed/skipped links"""

#     from core.models import ArchiveResult
#     from .search import index_links
#     # from workers.supervisord_util import start_cli_workers
    

#     check_data_folder()
#     # start_cli_workers()
#     new_links: List[Link] = [] # TODO: Remove input argument: only_new

#     extractors = extractors.split(",") if extractors else []

#     # Step 1: Filter for selected_links
#     print('[*] Finding matching Snapshots to update...')
#     print(f'    - Filtering by {" ".join(filter_patterns)} ({filter_type}) {before=} {after=} {status=}...')
#     matching_snapshots = list_links(
#         filter_patterns=filter_patterns,
#         filter_type=filter_type,
#         before=before,
#         after=after,
#     )
#     print(f'    - Checking {matching_snapshots.count()} snapshot folders for existing data with {status=}...')
#     matching_folders = list_folders(
#         links=matching_snapshots,
#         status=status,
#         out_dir=out_dir,
#     )
#     all_links = (link for link in matching_folders.values() if link)
#     print('    - Sorting by most unfinished -> least unfinished + date archived...')
#     all_links = sorted(all_links, key=lambda link: (ArchiveResult.objects.filter(snapshot__url=link.url).count(), link.timestamp))

#     if index_only:
#         for link in all_links:
#             write_link_details(link, out_dir=out_dir, skip_sql_index=True)
#         index_links(all_links, out_dir=out_dir)
#         return all_links
        
#     # Step 2: Run the archive methods for each link
#     to_archive = new_links if only_new else all_links
#     if resume:
#         to_archive = [
#             link for link in to_archive
#             if link.timestamp >= str(resume)
#         ]
#         if not to_archive:
#             stderr('')
#             stderr(f'[√] Nothing found to resume after {resume}', color='green')
#             return all_links

#     archive_kwargs = {
#         "out_dir": out_dir,
#     }
#     if extractors:
#         archive_kwargs["methods"] = extractors


#     archive_links(to_archive, overwrite=overwrite, **archive_kwargs)

#     # Step 4: Re-write links index with updated titles, icons, and resources
#     all_links = load_main_index(out_dir=out_dir)
#     return all_links
