from typing import Iterable
from collections import OrderedDict

from .schema import Link
from .util import (
    scheme,
    fuzzy_url,
    merge_links,
)


def validate_links(links: Iterable[Link]) -> Iterable[Link]:
    # remove chrome://, about:, mailto: etc.
    links = archivable_links(links)
    # deterministically sort the links based on timstamp, url
    links = sorted_links(links)
    # merge/dedupe duplicate timestamps & urls
    links = uniquefied_links(links)

    if not links:
        print('[X] No links found :(')
        raise SystemExit(1)

    return links


def archivable_links(links: Iterable[Link]) -> Iterable[Link]:
    """remove chrome://, about:// or other schemed links
       that cant be archived"""
    return (
        link
        for link in links
        if scheme(link.url) in ('http', 'https', 'ftp')
    )


def uniquefied_links(sorted_links: Iterable[Link]) -> Iterable[Link]:
    """ensures that all non-duplicate links have monotonically
       increasing timestamps"""

    unique_urls: OrderedDict[str, Link] = OrderedDict()

    for link in sorted_links:
        fuzzy = fuzzy_url(link.url)
        if fuzzy in unique_urls:
            # merge with any other links that share the same url
            link = merge_links(unique_urls[fuzzy], link)
        unique_urls[fuzzy] = link

    unique_timestamps: OrderedDict[str, Link] = OrderedDict()
    for link in unique_urls.values():
        new_link = link.overwrite(
            timestamp=lowest_uniq_timestamp(unique_timestamps, link.timestamp),
        )
        unique_timestamps[new_link.timestamp] = new_link

    return unique_timestamps.values()


def sorted_links(links: Iterable[Link]) -> Iterable[Link]:
    sort_func = lambda link: (link.timestamp.split('.', 1)[0], link.url) # noqa
    return sorted(links, key=sort_func, reverse=True)


def links_after_timestamp(
        links: Iterable[Link],
        resume: float = None
        ) -> Iterable[Link]:
    if not resume:
        yield from links
        return

    for link in links:
        try:
            if float(link.timestamp) <= resume:
                yield link
        except (ValueError, TypeError):
            print(
                'Resume value and all timestamp values must be valid numbers.'
            )


def lowest_uniq_timestamp(used_timestamps: OrderedDict, timestamp: str) -> str:
    """resolve duplicate timestamps by appending a decimal
       1234, 1234 -> 1234.1, 1234.2"""

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
