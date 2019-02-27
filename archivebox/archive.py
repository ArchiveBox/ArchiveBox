#!/usr/bin/env python3
# ArchiveBox
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/ArchiveBox

import os
import sys

from datetime import datetime
from peekable import Peekable


from parse import parse_links
from links import validate_links, links_after_timestamp
from archive_methods import archive_link, _RESULTS_TOTALS
from index import (
    write_links_index,
    parse_json_links_index,
)
from config import (
    ARCHIVE_DIR,
    ONLY_NEW,
    OUTPUT_DIR,
    REPO_DIR,
    ANSI,
    GIT_SHA,
)
from util import (
    check_dependencies,
    save_remote_source,
    save_stdin_source,
    pretty_path,
    migrate_data,
    check_links_structure,
)

__AUTHOR__ = 'Nick Sweeting <git@nicksweeting.com>'
__VERSION__ = GIT_SHA
__DESCRIPTION__ = 'ArchiveBox Usage:  Create a browsable html archive of a list of links.'
__DOCUMENTATION__ = 'https://github.com/pirate/ArchiveBox/wiki'


def print_help():
    print(__DESCRIPTION__)
    print("Documentation:     {}\n".format(__DOCUMENTATION__))
    print("Usage:")
    print("    ./bin/archivebox ~/Downloads/bookmarks_export.html\n")
    print("")
    print("    ./bin/archivebox https://example.com/feed.rss\n")
    print("")
    print("    echo 'https://examplecom' | ./bin/archivebox\n")


def load_links(archive_path=OUTPUT_DIR, import_path=None):
    """get new links from file and optionally append them to links in existing archive"""

    existing_links = []
    if archive_path:
        existing_links = parse_json_links_index(archive_path)
        check_links_structure(existing_links)

    new_links = []
    if import_path:
        # parse and validate the import file
        raw_links, parser_name = parse_links(import_path)
        new_links = validate_links(raw_links)
        check_links_structure(new_links)

    # merge existing links in archive_path and new links
    all_links = validate_links(existing_links + new_links)
    check_links_structure(all_links)
    num_new_links = len(all_links) - len(existing_links)

    if import_path and parser_name:
        print('    > Adding {} new links to index (parsed import as {})'.format(
            num_new_links,
            parser_name,
        ))

    return all_links, new_links


def update_archive(archive_path, links, source=None, resume=None, append=True):
    """update or create index.html+json given a path to an export file containing new links"""

    start_ts = datetime.now().timestamp()

    if resume:
        print('{green}[▶] [{}] Resuming archive downloading from {}...{reset}'.format(
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             resume,
             **ANSI,
        ))
    else:
        print('{green}[▶] [{}] Updating content for {} pages in archive...{reset}'.format(
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             len(links),
             **ANSI,
        ))

    check_links_structure(links)

    # prefetch the first link off the generator so that if we pause or fail
    # immediately we can show that we paused on the first link and not just None
    to_archive = Peekable(links_after_timestamp(links, resume))
    idx, link = 0, to_archive.peek(0)

    # loop over links and archive them
    try:
        check_dependencies()
        for idx, link in enumerate(to_archive):
            link_dir = os.path.join(ARCHIVE_DIR, link['timestamp'])
            archive_link(link_dir, link)

    except (KeyboardInterrupt, SystemExit, Exception) as e:
        print('\n{lightyellow}[X] [{now}] Downloading paused on link {timestamp} ({idx}/{total}){reset}'.format(
            **ANSI,
            now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            idx=idx+1,
            timestamp=link['timestamp'],
            total=len(links),
        ))
        print('    To view your archive, open: {}/index.html'.format(OUTPUT_DIR.replace(REPO_DIR + '/', '')))
        print('    Continue where you left off by running:')
        print('        {} {}'.format(
            pretty_path(sys.argv[0]),
            link['timestamp'],
        ))
        if not isinstance(e, KeyboardInterrupt):
            print()
            raise e
        raise SystemExit(1)

    # print timing information & summary
    end_ts = datetime.now().timestamp()
    seconds = end_ts - start_ts
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60, 2)
    else:
        duration = '{0:.2f} sec'.format(seconds, 2)

    print('{}[√] [{}] Update of {} pages complete ({}){}'.format(
        ANSI['green'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        len(links),
        duration,
        ANSI['reset'],
    ))
    print('    - {} entries skipped'.format(_RESULTS_TOTALS['skipped']))
    print('    - {} entries updated'.format(_RESULTS_TOTALS['succeded']))
    print('    - {} errors'.format(_RESULTS_TOTALS['failed']))
    print('    To view your archive, open: {}/index.html'.format(OUTPUT_DIR.replace(REPO_DIR + '/', '')))


if __name__ == '__main__':
    argc = len(sys.argv)

    if set(sys.argv).intersection(('-h', '--help', 'help')):
        print_help()
        raise SystemExit(0)

    migrate_data()

    source = sys.argv[1] if argc > 1 else None  # path of links file to import
    resume = sys.argv[2] if argc > 2 else None  # timestamp to resume dowloading from
   
    stdin_raw_text = ''

    if not sys.stdin.isatty():
        stdin_raw_text = sys.stdin.read()

    if source and stdin_raw_text:
        print(
            '[X] You should pass either a path as an argument, '
            'or pass a list of links via stdin, but not both.\n'
        )
        print_help()
        raise SystemExit(1)


    if argc == 1:
        source, resume = None, None
    elif argc == 2:
        if all(d.isdigit() for d in sys.argv[1].split('.')):
            # argv[1] is a resume timestamp
            source, resume = None, sys.argv[1]
        else:
            # argv[1] is a path to a file to import
            source, resume = sys.argv[1].strip(), None
    elif argc == 3:
        source, resume = sys.argv[1].strip(), sys.argv[2]
    else:
        print_help()
        raise SystemExit(1)

    # See if archive folder already exists
    for out_dir in (OUTPUT_DIR, 'bookmarks', 'pocket', 'pinboard', 'html'):
        if os.path.exists(out_dir):
            break
    else:
        out_dir = OUTPUT_DIR

    # Step 0: Download url to local file (only happens if a URL is specified instead of local path) 
    if source and any(source.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        source = save_remote_source(source)
    elif stdin_raw_text:
        source = save_stdin_source(stdin_raw_text)

    # Step 1: Parse the links and dedupe them with existing archive
    all_links, new_links = load_links(archive_path=out_dir, import_path=source)

    # Step 2: Write new index
    write_links_index(out_dir=out_dir, links=all_links)

    # Step 3: Run the archive methods for each link
    if ONLY_NEW:
        update_archive(out_dir, new_links, source=source, resume=resume, append=True)
    else:
        update_archive(out_dir, all_links, source=source, resume=resume, append=True)

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links, _ = load_links(archive_path=out_dir)
    write_links_index(out_dir=out_dir, links=all_links)
