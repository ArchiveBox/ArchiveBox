#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox remove'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from django.db.models import QuerySet

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, accept_stdin
from archivebox.index.schema import Link


def remove(filter_str: Optional[str]=None,
           filter_patterns: Optional[list[str]]=None,
           filter_type: str='exact',
           snapshots: Optional[QuerySet]=None,
           after: Optional[float]=None,
           before: Optional[float]=None,
           yes: bool=False,
           delete: bool=False,
           out_dir: Path=DATA_DIR) -> list[Link]:
    """Remove the specified URLs from the archive"""
    
    check_data_folder()

    if snapshots is None:
        if filter_str and filter_patterns:
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin, but not both.\n',
                color='red',
            )
            raise SystemExit(2)
        elif not (filter_str or filter_patterns):
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin.',
                color='red',
            )
            stderr()
            hint(('To remove all urls you can run:',
                'archivebox remove --filter-type=regex ".*"'))
            stderr()
            raise SystemExit(2)
        elif filter_str:
            filter_patterns = [ptn.strip() for ptn in filter_str.split('\n')]

    list_kwargs = {
        "filter_patterns": filter_patterns,
        "filter_type": filter_type,
        "after": after,
        "before": before,
    }
    if snapshots:
        list_kwargs["snapshots"] = snapshots

    log_list_started(filter_patterns, filter_type)
    timer = TimedProgress(360, prefix='      ')
    try:
        snapshots = list_links(**list_kwargs)
    finally:
        timer.end()


    if not snapshots.exists():
        log_removal_finished(0, 0)
        raise SystemExit(1)


    log_links = [link.as_link() for link in snapshots]
    log_list_finished(log_links)
    log_removal_started(log_links, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        for snapshot in snapshots:
            if delete:
                shutil.rmtree(snapshot.as_link().link_dir, ignore_errors=True)
    finally:
        timer.end()

    to_remove = snapshots.count()

    from .search import flush_search_index

    flush_search_index(snapshots=snapshots)
    remove_from_sql_main_index(snapshots=snapshots, out_dir=out_dir)
    all_snapshots = load_main_index(out_dir=out_dir)
    log_removal_finished(all_snapshots.count(), to_remove)
    
    return all_snapshots


@docstring(remove.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=remove.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--yes', # '-y',
        action='store_true',
        help='Remove links instantly without prompting to confirm.',
    )
    parser.add_argument(
        '--delete', # '-r',
        action='store_true',
        help=(
            "In addition to removing the link from the index, "
            "also delete its archived content and metadata folder."
        ),
    )
    parser.add_argument(
        '--before', #'-b',
        type=float,
        help="List only URLs bookmarked before the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--after', #'-a',
        type=float,
        help="List only URLs bookmarked after the given timestamp.",
        default=None,
    )
    parser.add_argument(
        '--filter-type',
        type=str,
        choices=('exact', 'substring', 'domain', 'regex','tag'),
        default='exact',
        help='Type of pattern matching to use when filtering URLs',
    )
    parser.add_argument(
        'filter_patterns',
        nargs='*',
        type=str,
        help='URLs matching this filter pattern will be removed from the index.'
    )
    command = parser.parse_args(args or ())
    
    filter_str = None
    if not command.filter_patterns:
        filter_str = accept_stdin(stdin)

    remove(
        filter_str=filter_str,
        filter_patterns=command.filter_patterns,
        filter_type=command.filter_type,
        before=command.before,
        after=command.after,
        yes=command.yes,
        delete=command.delete,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
