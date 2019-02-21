"""
In ArchiveBox, a Link represents a single entry that we track in the 
json index.  All links pass through all archiver functions and the latest,
most up-to-date canonical output for each is stored in "latest".


Link {
    timestamp: str,     (how we uniquely id links)        _   _  _ _  ___
    url: str,                                            | \ / \ |\| ' |
    base_url: str,                                       |_/ \_/ | |   |
    domain: str,                                          _   _ _ _ _  _
    tags: str,                                           |_) /| |\| | / `
    type: str,                                           |  /"| | | | \_,
    title: str,                                              ,-'"`-.
    sources: [str],                                     /// /  @ @  \ \\\\
    latest: {                                           \ :=| ,._,. |=:  /
        ...,                                            || ,\ \_../ /. ||
        pdf: 'output.pdf',                              ||','`-._))'`.`||
        wget: 'example.com/1234/index.html'             `-'     (/    `-'
    },
    history: {
        ...
        pdf: [
            {timestamp: 15444234325, status: 'skipped', result='output.pdf'},
            ...
        ],
        wget: [
            {timestamp: 11534435345, status: 'succeded', result='donuts.com/eat/them.html'}
        ]
    },
}

"""

from html import unescape
from collections import OrderedDict

from util import (
    merge_links,
    wget_output_path,
    check_link_structure,
    check_links_structure,
)


def validate_links(links):
    check_links_structure(links)
    links = archivable_links(links)  # remove chrome://, about:, mailto: etc.
    links = uniquefied_links(links)  # merge/dedupe duplicate timestamps & urls
    links = sorted_links(links)      # deterministically sort the links based on timstamp, url

    if not links:
        print('[X] No links found :(')
        raise SystemExit(1)

    for link in links:
        check_link_structure(link)

        link['title'] = unescape(link['title']) if link['title'] else None
        link['latest'] = link.get('latest') or {}

        latest = link['latest']
        if not link['latest'].get('wget'):
            link['latest']['wget'] = wget_output_path(link)

        if not link['latest'].get('pdf'):
            link['latest']['pdf'] = None

        if not link['latest'].get('screenshot'):
            link['latest']['screenshot'] = None

        if not link['latest'].get('dom'):
            link['latest']['dom'] = None

        if not latest.get('favicon'):
            latest['favicon'] = None

        if not link['latest'].get('title'):
            link['latest']['title'] = link['title']

    return list(links)


def archivable_links(links):
    """remove chrome://, about:// or other schemed links that cant be archived"""
    return (
        link
        for link in links
        if any(link['url'].lower().startswith(s) for s in ('http://', 'https://', 'ftp://'))
    )


def uniquefied_links(sorted_links):
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    """

    unique_urls = OrderedDict()

    lower = lambda url: url.lower().strip()
    without_www = lambda url: url.replace('://www.', '://', 1)
    without_trailing_slash = lambda url: url[:-1] if url[-1] == '/' else url.replace('/?', '?')

    for link in sorted_links:
        fuzzy_url = without_www(without_trailing_slash(lower(link['url'])))
        if fuzzy_url in unique_urls:
            # merge with any other links that share the same url
            link = merge_links(unique_urls[fuzzy_url], link)
        unique_urls[fuzzy_url] = link

    unique_timestamps = OrderedDict()
    for link in unique_urls.values():
        link['timestamp'] = lowest_uniq_timestamp(unique_timestamps, link['timestamp'])
        unique_timestamps[link['timestamp']] = link

    return unique_timestamps.values()


def sorted_links(links):
    sort_func = lambda link: (link['timestamp'].split('.', 1)[0], link['url'])
    return sorted(links, key=sort_func, reverse=True)


def links_after_timestamp(links, timestamp=None):
    if not timestamp:
        yield from links
        return

    for link in links:
        try:
            if float(link['timestamp']) <= float(timestamp):
                yield link
        except (ValueError, TypeError):
            print('Resume value and all timestamp values must be valid numbers.')


def lowest_uniq_timestamp(used_timestamps, timestamp):
    """resolve duplicate timestamps by appending a decimal 1234, 1234 -> 1234.1, 1234.2"""

    timestamp = timestamp.split('.')[0]
    nonce = 0

    # first try 152323423 before 152323423.0
    if timestamp not in used_timestamps:
        return timestamp

    new_timestamp = '{}.{}'.format(timestamp, nonce)
    while new_timestamp in used_timestamps:
        nonce += 1
        new_timestamp = '{}.{}'.format(timestamp, nonce)

    return new_timestamp
