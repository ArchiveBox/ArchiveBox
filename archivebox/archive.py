#!/usr/bin/env python3
"""
ArchiveBox command line application.

./archive and ./bin/archivebox both point to this file, 
but you can also run it directly using `python3 archive.py`

Usage & Documentation:
    https://github.com/pirate/ArchiveBox/Wiki
"""
__package__ = 'archivebox'

import os
import sys
import shutil

from typing import List, Optional

from .schema import Link
from .links import links_after_timestamp
from .index import write_links_index, load_links_index
from .archive_methods import archive_link
from .config import (
    ONLY_NEW,
    OUTPUT_DIR,
    VERSION,
    ANSI,
    CURL_VERSION,
    GIT_VERSION,
    WGET_VERSION,
    YOUTUBEDL_VERSION,
    CHROME_VERSION,
    USE_CURL,
    USE_WGET,
    USE_CHROME,
    CURL_BINARY,
    GIT_BINARY,
    WGET_BINARY,
    YOUTUBEDL_BINARY,
    CHROME_BINARY,
    FETCH_GIT,
    FETCH_MEDIA,
)
from .util import (
    enforce_types,
    save_remote_source,
    save_stdin_source,
)
from .logs import (
    log_archiving_started,
    log_archiving_paused,
    log_archiving_finished,
)

__AUTHOR__ = 'Nick Sweeting <git@nicksweeting.com>'
__VERSION__ = VERSION
__DESCRIPTION__ = 'ArchiveBox: The self-hosted internet archive.'
__DOCUMENTATION__ = 'https://github.com/pirate/ArchiveBox/wiki'



def print_help():
    print('ArchiveBox: The self-hosted internet archive.\n')
    print("Documentation:")
    print("    https://github.com/pirate/ArchiveBox/wiki\n")
    print("UI Usage:")
    print("    Open output/index.html to view your archive.\n")
    print("CLI Usage:")
    print("    mkdir data; cd data/")
    print("    archivebox init\n")
    print("    echo 'https://example.com/some/page' | archivebox add")
    print("    archivebox add https://example.com/some/other/page")
    print("    archivebox add --depth=1 ~/Downloads/bookmarks_export.html")
    print("    archivebox add --depth=1 https://example.com/feed.rss")
    print("    archivebox update --resume=15109948213.123")

def print_version():
    print('ArchiveBox v{}'.format(__VERSION__))
    print()
    print(
        '[{}] CURL:'.format('√' if USE_CURL else 'X').ljust(14),
        '{} --version\n'.format(shutil.which(CURL_BINARY)),
        ' '*13, CURL_VERSION, '\n',
    )
    print(
        '[{}] GIT:'.format('√' if FETCH_GIT else 'X').ljust(14),
        '{} --version\n'.format(shutil.which(GIT_BINARY)),
        ' '*13, GIT_VERSION, '\n',
    )
    print(
        '[{}] WGET:'.format('√' if USE_WGET else 'X').ljust(14),
        '{} --version\n'.format(shutil.which(WGET_BINARY)),
        ' '*13, WGET_VERSION, '\n',
    )
    print(
        '[{}] YOUTUBEDL:'.format('√' if FETCH_MEDIA else 'X').ljust(14),
        '{} --version\n'.format(shutil.which(YOUTUBEDL_BINARY)),
        ' '*13, YOUTUBEDL_VERSION, '\n',
    )
    print(
        '[{}] CHROME:'.format('√' if USE_CHROME else 'X').ljust(14),
        '{} --version\n'.format(shutil.which(CHROME_BINARY)),
        ' '*13, CHROME_VERSION, '\n',
    )


def main(args=None) -> None:
    if args is None:
        args = sys.argv

    if set(args).intersection(('-h', '--help', 'help')) or len(args) > 2:
        print_help()
        raise SystemExit(0)

    if set(args).intersection(('--version', 'version')):
        print_version()
        raise SystemExit(0)

    ### Handle CLI arguments
    #     ./archive bookmarks.html
    #     ./archive 1523422111.234
    import_path, resume = None, None
    if len(args) == 2:
        # if the argument is a string, it's a import_path file to import
        # if it's a number, it's a timestamp to resume archiving from
        if args[1].replace('.', '').isdigit():
            import_path, resume = None, args[1]
        else:
            import_path, resume = args[1], None

    ### Set up output folder
    if not os.path.exists(OUTPUT_DIR):
        print('{green}[+] Created a new archive directory: {}{reset}'.format(OUTPUT_DIR, **ANSI))
        os.makedirs(OUTPUT_DIR)
    else:
        not_empty = len(set(os.listdir(OUTPUT_DIR)) - {'.DS_Store'})
        index_exists = os.path.exists(os.path.join(OUTPUT_DIR, 'index.json'))
        if not_empty and not index_exists:
            print(
                ("{red}[X] Could not find index.json in the OUTPUT_DIR: {reset}{}\n\n"
                "    If you're trying to update an existing archive, you must set OUTPUT_DIR to or run archivebox from inside the archive folder you're trying to update.\n"
                "    If you're trying to create a new archive, you must run archivebox inside a completely empty directory."
                "\n\n"
                "    {lightred}Hint:{reset} To import a data folder created by an older version of ArchiveBox, \n"
                "    just cd into the folder and run the archivebox comamnd to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                ).format(OUTPUT_DIR, **ANSI)
            )
            raise SystemExit(1)

    ### Handle ingesting urls piped in through stdin
    # (.e.g if user does cat example_urls.txt | ./archive)
    if not sys.stdin.isatty():
        stdin_raw_text = sys.stdin.read()
        if stdin_raw_text and import_path:
            print(
                '[X] You should pass either a path as an argument, '
                'or pass a list of links via stdin, but not both.\n'
            )
            print_help()
            raise SystemExit(1)

        import_path = save_stdin_source(stdin_raw_text)

    ### Handle ingesting urls from a remote file/feed
    # (e.g. if an RSS feed URL is used as the import path) 
    if import_path and any(import_path.startswith(s) for s in ('http://', 'https://', 'ftp://')):
        import_path = save_remote_source(import_path)

    ### Run the main archive update process
    update_archive_data(import_path=import_path, resume=resume)


@enforce_types
def update_archive_data(import_path: Optional[str]=None, resume: Optional[float]=None) -> List[Link]:
    """The main ArchiveBox entrancepoint. Everything starts here."""

    # Step 1: Load list of links from the existing index
    #         merge in and dedupe new links from import_path
    all_links, new_links = load_links_index(out_dir=OUTPUT_DIR, import_path=import_path)

    # Step 2: Write updated index with deduped old and new links back to disk
    write_links_index(links=list(all_links), out_dir=OUTPUT_DIR)

    # Step 3: Run the archive methods for each link
    links = new_links if ONLY_NEW else all_links
    log_archiving_started(len(links), resume)
    idx: int = 0
    link: Optional[Link] = None
    try:
        for idx, link in enumerate(links_after_timestamp(links, resume)):
            archive_link(link, link_dir=link.link_dir)

    except KeyboardInterrupt:
        log_archiving_paused(len(links), idx, link.timestamp if link else '0')
        raise SystemExit(0)

    except:
        print()
        raise    

    log_archiving_finished(len(links))

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links, _ = load_links_index(out_dir=OUTPUT_DIR)
    write_links_index(links=list(all_links), out_dir=OUTPUT_DIR, finished=True)
    return all_links

if __name__ == '__main__':
    main(sys.argv)
