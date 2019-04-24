__package__ = 'archivebox.legacy'

import os
import json

from typing import List, Tuple, Optional, Iterable
from collections import OrderedDict
from contextlib import contextmanager

from .schema import Link, ArchiveResult
from .config import (
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    OUTPUT_DIR,
    TIMEOUT,
    URL_BLACKLIST_PTN,
    ANSI,
    stderr,
)
from .storage.html import write_html_main_index, write_html_link_details
from .storage.json import (
    parse_json_main_index,
    write_json_main_index,
    parse_json_link_details, 
    write_json_link_details,
)
from .storage.sql import (
    write_sql_main_index,
    parse_sql_main_index,
)
from .util import (
    scheme,
    enforce_types,
    TimedProgress,
    atomic_write,
    ExtendedEncoder,
)
from .parse import parse_links
from .logs import (
    log_indexing_process_started,
    log_indexing_process_finished,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_started,
    log_parsing_finished,
)

### Link filtering and checking

@enforce_types
def merge_links(a: Link, b: Link) -> Link:
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    assert a.base_url == b.base_url, 'Cannot merge two links with different URLs'

    # longest url wins (because a fuzzy url will always be shorter)
    url = a.url if len(a.url) > len(b.url) else b.url

    # best title based on length and quality
    possible_titles = [
        title
        for title in (a.title, b.title)
        if title and title.strip() and '://' not in title
    ]
    title = None
    if len(possible_titles) == 2:
        title = max(possible_titles, key=lambda t: len(t))
    elif len(possible_titles) == 1:
        title = possible_titles[0]

    # earliest valid timestamp
    timestamp = (
        a.timestamp
        if float(a.timestamp or 0) < float(b.timestamp or 0) else
        b.timestamp
    )

    # all unique, truthy tags
    tags_set = (
        set(tag.strip() for tag in (a.tags or '').split(','))
        | set(tag.strip() for tag in (b.tags or '').split(','))
    )
    tags = ','.join(tags_set) or None

    # all unique source entries
    sources = list(set(a.sources + b.sources))

    # all unique history entries for the combined archive methods
    all_methods = set(list(a.history.keys()) + list(a.history.keys()))
    history = {
        method: (a.history.get(method) or []) + (b.history.get(method) or [])
        for method in all_methods
    }
    for method in all_methods:
        deduped_jsons = {
            json.dumps(result, sort_keys=True, cls=ExtendedEncoder)
            for result in history[method]
        }
        history[method] = list(reversed(sorted(
            (ArchiveResult.from_json(json.loads(result)) for result in deduped_jsons),
            key=lambda result: result.start_ts,
        )))

    return Link(
        url=url,
        timestamp=timestamp,
        title=title,
        tags=tags,
        sources=sources,
        history=history,
    )


@enforce_types
def validate_links(links: Iterable[Link]) -> Iterable[Link]:
    links = archivable_links(links)  # remove chrome://, about:, mailto: etc.
    links = sorted_links(links)      # deterministically sort the links based on timstamp, url
    links = uniquefied_links(links)  # merge/dedupe duplicate timestamps & urls

    if not links:
        stderr('{red}[X] No links found in index.{reset}'.format(**ANSI))
        stderr('    To add a link to your archive, run:')
        stderr("        archivebox add 'https://example.com'")
        stderr()
        stderr('    For more usage and examples, run:')
        stderr('        archivebox help')
        raise SystemExit(1)

    return links


@enforce_types
def archivable_links(links: Iterable[Link]) -> Iterable[Link]:
    """remove chrome://, about:// or other schemed links that cant be archived"""
    for link in links:
        scheme_is_valid = scheme(link.url) in ('http', 'https', 'ftp')
        not_blacklisted = (not URL_BLACKLIST_PTN.match(link.url)) if URL_BLACKLIST_PTN else True
        if scheme_is_valid and not_blacklisted:
            yield link


@enforce_types
def uniquefied_links(sorted_links: Iterable[Link]) -> Iterable[Link]:
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    """

    unique_urls: OrderedDict[str, Link] = OrderedDict()

    for link in sorted_links:
        if link.base_url in unique_urls:
            # merge with any other links that share the same url
            link = merge_links(unique_urls[link.base_url], link)
        unique_urls[link.base_url] = link

    unique_timestamps: OrderedDict[str, Link] = OrderedDict()
    for link in unique_urls.values():
        new_link = link.overwrite(
            timestamp=lowest_uniq_timestamp(unique_timestamps, link.timestamp),
        )
        unique_timestamps[new_link.timestamp] = new_link

    return unique_timestamps.values()


@enforce_types
def sorted_links(links: Iterable[Link]) -> Iterable[Link]:
    sort_func = lambda link: (link.timestamp.split('.', 1)[0], link.url)
    return sorted(links, key=sort_func, reverse=True)


@enforce_types
def links_after_timestamp(links: Iterable[Link], resume: Optional[float]=None) -> Iterable[Link]:
    if not resume:
        yield from links
        return

    for link in links:
        try:
            if float(link.timestamp) <= resume:
                yield link
        except (ValueError, TypeError):
            print('Resume value and all timestamp values must be valid numbers.')


@enforce_types
def lowest_uniq_timestamp(used_timestamps: OrderedDict, timestamp: str) -> str:
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



### Main Links Index

@contextmanager
@enforce_types
def timed_index_update(out_path: str):
    log_indexing_started(out_path)
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    try:
        yield
    finally:
        timer.end()

    assert os.path.exists(out_path), f'Failed to write index file: {out_path}'
    log_indexing_finished(out_path)


@enforce_types
def write_main_index(links: List[Link], out_dir: str=OUTPUT_DIR, finished: bool=False) -> None:
    """create index.html file for a given list of links"""

    log_indexing_process_started(len(links))

    with timed_index_update(os.path.join(out_dir, SQL_INDEX_FILENAME)):
        write_sql_main_index(links, out_dir=out_dir)

    with timed_index_update(os.path.join(out_dir, JSON_INDEX_FILENAME)):
        write_json_main_index(links, out_dir=out_dir)

    with timed_index_update(os.path.join(out_dir, HTML_INDEX_FILENAME)):
        write_html_main_index(links, out_dir=out_dir, finished=finished)

    log_indexing_process_finished()


@enforce_types
def load_main_index(out_dir: str=OUTPUT_DIR, warn: bool=True) -> List[Link]:
    """parse and load existing index with any new links from import_path merged in"""

    all_links: List[Link] = []
    all_links = list(parse_json_main_index(out_dir))
    links_from_sql = list(parse_sql_main_index(out_dir))

    if warn and not set(l.url for l in all_links) == set(l.url for l in links_from_sql):
        stderr('{red}[!] Warning: SQL index does not match JSON index!{reset}'.format(**ANSI))
        stderr('    To repair the index and re-import any orphaned links run:')
        stderr('        archivebox init')

    return all_links

@enforce_types
def load_main_index_meta(out_dir: str=OUTPUT_DIR) -> Optional[dict]:
    index_path = os.path.join(out_dir, JSON_INDEX_FILENAME)
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            meta_dict = json.load(f)
            meta_dict.pop('links')
            return meta_dict

    return None

@enforce_types
def import_new_links(existing_links: List[Link], import_path: str) -> Tuple[List[Link], List[Link]]:
    new_links: List[Link] = []

    # parse and validate the import file
    log_parsing_started(import_path)
    raw_links, parser_name = parse_links(import_path)
    new_links = list(validate_links(raw_links))

    # merge existing links in out_dir and new links
    all_links = list(validate_links(existing_links + new_links))

    if parser_name:
        num_parsed = len(raw_links)
        num_new_links = len(all_links) - len(existing_links)
        log_parsing_finished(num_parsed, num_new_links, parser_name)

    return all_links, new_links


@enforce_types
def patch_main_index(link: Link, out_dir: str=OUTPUT_DIR) -> None:
    """hack to in-place update one row's info in the generated index files"""

    # TODO: remove this ASAP, it's ugly, error-prone, and potentially dangerous

    title = link.title or link.latest_outputs(status='succeeded')['title']
    successful = link.num_outputs

    # Patch JSON main index
    json_file_links = parse_json_main_index(out_dir)
    patched_links = []
    for saved_link in json_file_links:
        if saved_link.url == link.url:
            patched_links.append(saved_link.overwrite(
                title=title,
                history=link.history,
                updated=link.updated,
            ))
        else:
            patched_links.append(saved_link)
    
    write_json_main_index(patched_links, out_dir=out_dir)

    # Patch HTML main index
    html_path = os.path.join(out_dir, 'index.html')
    with open(html_path, 'r') as f:
        html = f.read().split('\n')
    for idx, line in enumerate(html):
        if title and ('<span data-title-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(title)
        elif successful and ('<span data-number-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(successful)
            break

    atomic_write('\n'.join(html), html_path)


### Link Details Index

@enforce_types
def write_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    out_dir = out_dir or link.link_dir

    write_json_link_details(link, out_dir=out_dir)
    write_html_link_details(link, out_dir=out_dir)


@enforce_types
def load_link_details(link: Link, out_dir: Optional[str]=None) -> Link:
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    out_dir = out_dir or link.link_dir

    existing_link = parse_json_link_details(out_dir)
    if existing_link:
        return merge_links(existing_link, link)

    return link
