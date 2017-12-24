#!/usr/bin/env python3
# Bookmark Archiver
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

import os
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

def print_help():
    print(__DESCRIPTION__)
    print("Documentation:     {}\n".format(__DOCUMENTATION__))
    print("Usage:")
    print("    ./archive.py ~/Downloads/bookmarks_export.html\n")


def get_links(new_links_file_path, archive_path=HTML_FOLDER):
    """get new links from file and optionally append them to links in existing archive"""
    # parse and validate the new_links_file
    raw_links = parse_links(new_links_file_path)
    valid_links = validate_links(raw_links)

    # merge existing links in archive_path and new links
    existing_links = []
    if archive_path:
        existing_links = parse_json_links_index(archive_path)
        valid_links = validate_links(existing_links + valid_links)
    
    num_new_links = len(valid_links) - len(existing_links)
    print('[*] [{}] Adding {} new links from {} to index'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        num_new_links,
        new_links_file_path,
    ))

    return valid_links

def update_archive(archive_path, links, source=None, resume=None, append=True):
    """update or create index.html+json given a path to an export file containing new links"""

    start_ts = datetime.now().timestamp()

    # loop over links and archive them
    archive_links(archive_path, links, source=source, resume=resume)

    # print timing information & summary
    end_ts = datetime.now().timestamp()
    seconds = end_ts - start_ts
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60, 2)
    else:
        duration = '{0:.2f} sec'.format(seconds, 2)

    print('{}[√] [{}] Archive update complete ({}){}'.format(
        ANSI['green'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        duration,
        ANSI['reset'],
    ))
    print('    - {} entries skipped'.format(_RESULTS_TOTALS['skipped']))
    print('    - {} entries updated'.format(_RESULTS_TOTALS['succeded']))
    print('    - {} errors'.format(_RESULTS_TOTALS['failed']))


if __name__ == '__main__':
    argc = len(sys.argv)

    if argc < 2 or set(sys.argv).intersection('-h', '--help', 'help'):
        print_help()
        raise SystemExit(0)

    source = sys.argv[1]                        # path to export file
    resume = sys.argv[2] if argc > 2 else None  # timestamp to resume dowloading from
   
    # See if archive folder already exists
    for out_folder in (HTML_FOLDER, 'bookmarks', 'pocket', 'pinboard', 'html'):
        if os.path.exists(out_folder):
            break
    else:
        out_folder = HTML_FOLDER

    archive_path = os.path.join(out_folder, 'archive')

    # Download url to local file (only happens if a URL is specified instead of local path) 
    if any(source.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        source = download_url(source)

    # Parse the links and dedupe them with existing archive
    links = get_links(source, archive_path=archive_path)

    # Verify folder structure is 1:1 with index
    cleanup_archive(archive_path, links)

    # Run the archive methods for each link
    update_archive(archive_path, links, source=source, resume=resume, append=True)

    # Write new index
    write_links_index(archive_path, links)
