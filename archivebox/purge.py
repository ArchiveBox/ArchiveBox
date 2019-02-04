#!/usr/bin/env python3

import re
from argparse import ArgumentParser
from os.path import exists, join
from shutil import rmtree
from typing import List

from archive import parse_json_link_index
from config import ARCHIVE_DIR, OUTPUT_DIR
from index import write_html_links_index, write_json_links_index


def cleanup_index(regexes: List[str], proceed: bool, delete: bool) -> None:
    if not exists(join(OUTPUT_DIR, 'index.json')):
        exit('index.json is missing; nothing to do')

    compiled = [re.compile(r) for r in regexes]
    links = parse_json_link_index(OUTPUT_DIR)['links']
    filtered = []
    remaining = []

    for l in links:
        url = l['url']
        for r in compiled:
            if r.search(url):
                filtered.append((l, r))
                break
        else:
            remaining.append(l)

    if not filtered:
        exit('Search did not match any entries.')

    print('Filtered out {}/{} urls:'.format(len(filtered), len(links)))

    for link, regex in filtered:
        url = link['url']
        print(' {url} via {regex}'.format(url=url, regex=regex.pattern))

    if not proceed:
        answer = input('Remove {} entries from index? [y/n] '.format(
            len(filtered)))
        proceed = answer.strip().lower() in ('y', 'yes')

    if not proceed:
        exit('Aborted')

    write_json_links_index(OUTPUT_DIR, remaining)
    write_html_links_index(OUTPUT_DIR, remaining)

    if delete:
        for link, _ in filtered:
            data_dir = join(ARCHIVE_DIR, link['timestamp'])
            if exists(data_dir):
                rmtree(data_dir)


if __name__ == '__main__':
    p = ArgumentParser('Index purging tool')
    p.add_argument(
        '--regex',
        '-r',
        action='append',
        help='Regular expression matching URLs to purge',
    )
    p.add_argument(
        '--delete',
        '-d',
        action='store_true',
        default=False,
        help='Delete webpage files from archive',
    )
    p.add_argument(
        '--yes',
        '-y',
        action='store_true',
        default=False,
        help='Do not prompt for confirmation',
    )

    args = p.parse_args()
    if args.regex:
        cleanup_index(args.regex, proceed=args.yes, delete=args.delete)
    else:
        p.print_help()
