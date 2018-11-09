#!/usr/bin/env python3
import argparse
import re
from typing import List

from archive import parse_json_link_index
from config import OUTPUT_DIR
from index import write_json_links_index


def cleanup_index(patterns: List[str], yes=False):
    regexes = [re.compile(p) for p in patterns]

    index = parse_json_link_index(OUTPUT_DIR)
    links = index['links']

    filtered = []
    remaining = []
    for l in links:
        url = l['url']
        for r in regexes:
            if r.search(url):
                filtered.append((l, r))
                break
        else:
            remaining.append(l)


    print("Filtered out {}/{} urls:".format(len(filtered), len(links)))
    for link, regex in filtered:
        url = link['url']
        print(" {url} via {regex}".format(url=url, regex=regex.pattern))

    proceed = False
    if yes:
        proceed = True
    else:
        res = input("Remove {} entries from index? [y/n] ".format(len(filtered)))
        proceed = res.strip().lower() in ('y', 'yes')

    if proceed:
        write_json_links_index(OUTPUT_DIR, remaining)
    else:
        exit('aborting')


if __name__ == '__main__':
    p = argparse.ArgumentParser('Index purging tool')
    p.add_argument('--regex', '-r', action='append', help='Python regex to filter out')
    p.add_argument('--yes', action='store_true', default=False, help='Do not propmpt for confirmation')

    args = p.parse_args()
    regexes = args.regex
    cleanup_index(regexes, yes=args.yes)
