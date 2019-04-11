#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox init'
__description__ = 'Initialize a new ArchiveBox collection in the current directory'

import os
import sys
import argparse

from ..legacy.util import reject_stdin
from ..legacy.index import write_links_index
from ..legacy.config import (
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    DATABASE_DIR,
    ANSI,
    stderr,
)


def init(output_dir: str=OUTPUT_DIR):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    harmless_files = {'.DS_Store', '.venv', 'venv', 'virtualenv', '.virtualenv'}
    is_empty = not len(set(os.listdir(output_dir)) - harmless_files)
    existing_index = os.path.exists(os.path.join(output_dir, 'index.json'))

    if not is_empty:
        if existing_index:
            stderr('[√] You already have an archive setup up in this folder. To add new links, you can run:')
            stderr('    archivebox add https://example.com')
            stderr()
            stderr('[i] Fore more usage and examples, run "archivebox help" or visit:')
            stderr('    https://github.com/pirate/ArchiveBox/wiki/Usage')
            # TODO: import old archivebox version's archive data folder

            raise SystemExit(1)
        else:
            stderr(
                ("{red}[X] This folder already has files in it. You must run init inside a completely empty directory.{reset}"
                "\n\n"
                "    {lightred}Hint:{reset} To import a data folder created by an older version of ArchiveBox, \n"
                "    just cd into the folder and run the archivebox command to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                ).format(output_dir, **ANSI)
            )
            raise SystemExit(1)


    stderr('{green}[+] Initializing new archive directory: {}{reset}'.format(output_dir, **ANSI))
    os.makedirs(SOURCES_DIR)
    stderr(f'    > {SOURCES_DIR}')
    os.makedirs(ARCHIVE_DIR)
    stderr(f'    > {ARCHIVE_DIR}')
    os.makedirs(DATABASE_DIR)
    stderr(f'    > {DATABASE_DIR}')

    write_links_index([], out_dir=OUTPUT_DIR, finished=True)

    stderr('{green}[√] Done.{reset}'.format(**ANSI))


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args)
    reject_stdin(__command__)

    init()
    

if __name__ == '__main__':
    main()
