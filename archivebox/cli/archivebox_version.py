#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox version'
__description__ = 'Print the ArchiveBox version and dependency information'

import sys
import shutil
import argparse

from ..legacy.util import reject_stdin
from ..legacy.config import (
    VERSION,

    REPO_DIR,
    PYTHON_DIR,
    LEGACY_DIR,
    TEMPLATES_DIR,
    OUTPUT_DIR,
    SOURCES_DIR,
    ARCHIVE_DIR,
    DATABASE_DIR,

    USE_CURL,
    USE_WGET,
    USE_CHROME,
    FETCH_GIT,
    FETCH_MEDIA,

    DJANGO_BINARY,
    CURL_BINARY,
    GIT_BINARY,
    WGET_BINARY,
    YOUTUBEDL_BINARY,
    CHROME_BINARY,

    DJANGO_VERSION,
    CURL_VERSION,
    GIT_VERSION,
    WGET_VERSION,
    YOUTUBEDL_VERSION,
    CHROME_VERSION,
)


def main(args=None):
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
    )
    parser.parse_args(args)
    reject_stdin(__command__)
    
    print('ArchiveBox v{}'.format(VERSION))
    print()
    print('[i] Folder locations:')
    print('    REPO_DIR:      ', REPO_DIR)
    print('    PYTHON_DIR:    ', PYTHON_DIR)
    print('    LEGACY_DIR:    ', LEGACY_DIR)
    print('    TEMPLATES_DIR: ', TEMPLATES_DIR)
    print()
    print('    OUTPUT_DIR:    ', OUTPUT_DIR)
    print('    SOURCES_DIR:   ', SOURCES_DIR)
    print('    ARCHIVE_DIR:   ', ARCHIVE_DIR)
    print('    DATABASE_DIR:  ', DATABASE_DIR)
    print()
    print(
        '[√] Django:'.ljust(14),
        'python3 {} --version\n'.format(DJANGO_BINARY),
        ' '*13, DJANGO_VERSION, '\n',
    )
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


if __name__ == '__main__':
    main()
