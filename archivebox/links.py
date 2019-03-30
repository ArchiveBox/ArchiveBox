"""
In ArchiveBox, a Link represents a single entry that we track in the 
json index.  All links pass through all archiver functions and the latest,
most up-to-date canonical output for each is stored in "latest".

Link {
    timestamp: str,     (how we uniquely id links)    
    url: str,                                         
    title: str,                                       
    tags: str,                                        
    sources: [str],                                   
    history: {
        pdf: [
            {start_ts, end_ts, duration, cmd, pwd, status, output},
            ...
        ],
        ...
    },
}
"""

from html import unescape
from collections import OrderedDict

from util import (
    scheme,
    merge_links,
    check_link_structure,
    check_links_structure,
)

from config import (
    URL_BLACKLIST,
)

def validate_links(links):
    check_links_structure(links)
    links = archivable_links(links)     # remove chrome://, about:, mailto: etc.
    links = uniquefied_links(links)     # merge/dedupe duplicate timestamps & urls
    links = sorted_links(links)         # deterministically sort the links based on timstamp, url
    
    if not links:
        print('[X] No links found :(')
        raise SystemExit(1)

    for link in links:
        link['title'] = unescape(link['title'].strip()) if link['title'] else None
        check_link_structure(link)

    return list(links)


def archivable_links(links):
    """remove chrome://, about:// or other schemed links that cant be archived"""
    for link in links:
        scheme_is_valid = scheme(link['url']) in ('http', 'https', 'ftp')
        not_blacklisted = (not URL_BLACKLIST.match(link['url'])) if URL_BLACKLIST else True
        if scheme_is_valid and not_blacklisted:
            yield link


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
    
    
