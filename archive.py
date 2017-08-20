#!/usr/bin/env python3
# Bookmark Archiver
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

import os
import sys

from datetime import datetime

from parse import parse_export
from index import dump_index
from fetch import dump_website
from config import (
    ARCHIVE_PERMISSIONS,
    ARCHIVE_DIR,
    ANSI,
    check_dependencies,
)

DESCRIPTION = 'Bookmark Archiver: Create a browsable html archive of a list of links.'
__DOCUMENTATION__ = 'https://github.com/pirate/bookmark-archiver'


def create_archive(export_file, service=None, resume=None):
    """update or create index.html and download archive of all links"""

    print('[*] [{}] Starting archive from {} export file.'.format(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        export_file,
    ))

    with open(export_file, 'r', encoding='utf-8') as f:
        links, service = parse_export(f, service=service)

    if resume:
        try:
            links = [
                link
                for link in links
                if float(link['timestamp']) >= float(resume)
            ]
        except TypeError:
            print('Resume value and all timestamp values must be valid numbers.')

    if not links or not service:
        print('[X] No links found in {}, is it a {} export file?'.format(export_file, service))
        raise SystemExit(1)

    if not os.path.exists(os.path.join(ARCHIVE_DIR, service)):
        os.makedirs(os.path.join(ARCHIVE_DIR, service))

    if not os.path.exists(os.path.join(ARCHIVE_DIR, service, 'archive')):
        os.makedirs(os.path.join(ARCHIVE_DIR, service, 'archive'))

    dump_index(links, service)
    check_dependencies()
    try:
        for link in links:
            dump_website(link, service)
    except (KeyboardInterrupt, SystemExit, Exception) as e:
        print('{red}[X] Archive creation stopped.{reset}'.format(**ANSI))
        print('    Continue where you left off by running:')
        print('       ./archive.py {} {} {}'.format(
            export_file,
            service,
            link['timestamp'],
        ))
        if not isinstance(e, KeyboardInterrupt):
            raise e
        raise SystemExit(1)

    print('{}[√] [{}] Archive update complete.{}'.format(ANSI['green'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ANSI['reset']))


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

    export_file = sys.argv[1]                                       # path to export file
    export_type = sys.argv[2] if argc > 2 else None                 # select export_type for file format select
    resume_from = sys.argv[3] if argc > 3 else None                 # timestamp to resume dowloading from

    create_archive(export_file, service=export_type, resume=resume_from)
