#!/usr/bin/env python3
# Bookmark Archiver
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

import sys

from datetime import datetime

from parse import parse_links
from links import validate_links
from archive_methods import archive_links, _RESULTS_TOTALS
from index import (
    write_links_index,
    write_link_index,
    parse_json_links_index,
    parse_json_link_index,
)
from config import (
    ARCHIVE_PERMISSIONS,
    HTML_FOLDER,
    ARCHIVE_FOLDER,
    ANSI,
    TIMEOUT,
)
from util import (
    download_url,
    check_dependencies,
    progress,
    cleanup_archive,
)

__DESCRIPTION__ = 'Bookmark Archiver: Create a browsable html archive of a list of links.'
__DOCUMENTATION__ = 'https://github.com/pirate/bookmark-archiver'


def update_archive(export_path, links, resume=None, append=True):
    """update or create index.html+json given a path to an export file containing new links"""

    start_ts = datetime.now().timestamp()

    # loop over links and archive them
    archive_links(ARCHIVE_FOLDER, links, export_path, resume=resume)

    # print timing information & summary
    end_ts = datetime.now().timestamp()
    seconds = round(end_ts - start_ts, 1)
    duration = '{} min'.format(seconds / 60) if seconds > 60 else '{} sec'.format(seconds)
    print('{}[√] [{}] Archive update complete ({}){}'.format(
        ANSI['green'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        duration,
        ANSI['reset'],
    ))
    print('    - {} entries skipped'.format(_RESULTS_TOTALS['skipped']))
    print('    - {} entries updated'.format(_RESULTS_TOTALS['succeded']))
    print('    - {} errors'.format(_RESULTS_TOTALS['failed']))


def update_index(export_path, resume=None, append=True):
    """handling parsing new links into the json index, returns a set of clean links"""

    # parse an validate the export file
    new_links = validate_links(parse_links(export_path))

    # load existing links if archive folder is present
    existing_links = []
    if append:
        existing_links = parse_json_links_index(HTML_FOLDER)
        links = validate_links(existing_links + new_links)
        

    # merge existing links and new links
    num_new_links = len(links) - len(existing_links)
    print('[*] [{}] Adding {} new links from {} to index'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        num_new_links,
        export_path,
    ))

    # write link index html & json
    write_links_index(HTML_FOLDER, links)

    return links


if __name__ == '__main__':
    argc = len(sys.argv)

    if argc < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(__DESCRIPTION__)
        print("Documentation:     {}".format(__DOCUMENTATION__))
        print("")
        print("Usage:")
        print("    ./archive.py ~/Downloads/bookmarks_export.html")
        print("")
        raise SystemExit(0)

    export_path = sys.argv[1]                        # path to export file
    resume_from = sys.argv[2] if argc > 2 else None  # timestamp to resume dowloading from

    if any(export_path.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        export_path = download_url(export_path)

    links = update_index(export_path, resume=resume_from, append=True)

    # make sure folder structure is sane
    cleanup_archive(ARCHIVE_FOLDER, links)
    update_archive(export_path, links, resume=resume_from, append=True)
