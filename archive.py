#!/usr/bin/env python3
# Bookmark Archiver
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

import sys

from datetime import datetime

from links import validate_links
from parse import parse_export
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
)

DESCRIPTION = 'Bookmark Archiver: Create a browsable html archive of a list of links.'
__DOCUMENTATION__ = 'https://github.com/pirate/bookmark-archiver'



def update_archive(export_path, resume=None, append=True):
    """update or create index.html and download archive of all links"""

    start_ts = datetime.now().timestamp()

    # parse an validate the export file
    new_links = validate_links(parse_export(export_path))

    # load existing links if archive folder is present
    if append:
        existing_links = parse_json_links_index(HTML_FOLDER)
        links = validate_links(existing_links + new_links)
    else:
        existing_links = []

    # merge existing links and new links
    num_new_links = len(links) - len(existing_links)
    print('[*] [{}] Adding {} new links from {} to index'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        num_new_links,
        export_path,
    ))

    # write link index html & json
    write_links_index(HTML_FOLDER, links)

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
    print('    - {} skipped'.format(_RESULTS_TOTALS['skipped']))
    print('    - {} updates'.format(_RESULTS_TOTALS['succeded']))
    print('    - {} errors'.format(_RESULTS_TOTALS['failed']))


if __name__ == '__main__':
    argc = len(sys.argv)

    if argc < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(DESCRIPTION)
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

    update_archive(export_path, resume=resume_from)
