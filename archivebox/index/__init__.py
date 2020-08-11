__package__ = 'archivebox.index'

import re
import os
import shutil
import json as pyjson

from itertools import chain
from typing import List, Tuple, Dict, Optional, Iterable
from collections import OrderedDict
from contextlib import contextmanager

from ..system import atomic_write
from ..util import (
    scheme,
    enforce_types,
    ExtendedEncoder,
)
from ..config import (
    ARCHIVE_DIR_NAME,
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
    OUTPUT_DIR,
    TIMEOUT,
    URL_BLACKLIST_PTN,
    ANSI,
    stderr,
    OUTPUT_PERMISSIONS
)
from ..logging_util import (
    TimedProgress,
    log_indexing_process_started,
    log_indexing_process_finished,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_finished,
    log_deduping_finished,
)

from .schema import Link, ArchiveResult
from .html import (
    write_html_main_index,
    write_html_link_details,
)
from .json import (
    parse_json_main_index,
    write_json_main_index,
    parse_json_link_details, 
    write_json_link_details,
)
from .sql import (
    write_sql_main_index,
    parse_sql_main_index,
    write_sql_link_details,
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
            pyjson.dumps(result, sort_keys=True, cls=ExtendedEncoder)
            for result in history[method]
        }
        history[method] = list(reversed(sorted(
            (ArchiveResult.from_json(pyjson.loads(result)) for result in deduped_jsons),
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
def validate_links(links: Iterable[Link]) -> List[Link]:
    timer = TimedProgress(TIMEOUT * 4)
    try:
        links = archivable_links(links)  # remove chrome://, about:, mailto: etc.
        links = sorted_links(links)      # deterministically sort the links based on timstamp, url
        links = uniquefied_links(links)  # merge/dedupe duplicate timestamps & urls
    finally:
        timer.end()

    return list(links)


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
        os.chmod(os.path.join(out_dir, SQL_INDEX_FILENAME), int(OUTPUT_PERMISSIONS, base=8)) # set here because we don't write it with atomic writes


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
            meta_dict = pyjson.load(f)
            meta_dict.pop('links')
            return meta_dict

    return None


@enforce_types
def parse_links_from_source(source_path: str) -> Tuple[List[Link], List[Link]]:

    from ..parsers import parse_links

    new_links: List[Link] = []

    # parse and validate the import file
    raw_links, parser_name = parse_links(source_path)
    new_links = validate_links(raw_links)

    if parser_name:
        num_parsed = len(raw_links)
        log_parsing_finished(num_parsed, parser_name)

    return new_links


@enforce_types
def dedupe_links(existing_links: List[Link],
                 new_links: List[Link]) -> Tuple[List[Link], List[Link]]:

    # merge existing links in out_dir and new links
    all_links = validate_links(existing_links + new_links)
    all_link_urls = {link.url for link in existing_links}

    new_links = [
        link for link in new_links
        if link.url not in all_link_urls
    ]

    all_links_deduped = {link.url: link for link in all_links}
    for i in range(len(new_links)):
        if new_links[i].url in all_links_deduped.keys():
            new_links[i] = all_links_deduped[new_links[i].url]
    log_deduping_finished(len(new_links))

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
        html = f.read().splitlines()

    for idx, line in enumerate(html):
        if title and ('<span data-title-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(title)
        elif successful and ('<span data-number-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(successful)
            break

    atomic_write(html_path, '\n'.join(html))


### Link Details Index

@enforce_types
def write_link_details(link: Link, out_dir: Optional[str]=None, skip_sql_index: bool=False) -> None:
    out_dir = out_dir or link.link_dir

    write_json_link_details(link, out_dir=out_dir)
    write_html_link_details(link, out_dir=out_dir)
    if not skip_sql_index:
        write_sql_link_details(link)


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



LINK_FILTERS = {
    'exact': lambda link, pattern: (link.url == pattern) or (link.base_url == pattern),
    'substring': lambda link, pattern: pattern in link.url,
    'regex': lambda link, pattern: bool(re.match(pattern, link.url)),
    'domain': lambda link, pattern: link.domain == pattern,
}

@enforce_types
def link_matches_filter(link: Link, filter_patterns: List[str], filter_type: str='exact') -> bool:
    for pattern in filter_patterns:
        try:
            if LINK_FILTERS[filter_type](link, pattern):
                return True
        except Exception:
            stderr()
            stderr(
                f'[X] Got invalid pattern for --filter-type={filter_type}:',
                color='red',
            )
            stderr(f'    {pattern}')
            raise SystemExit(2)

    return False


def get_indexed_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links without checking archive status or data directory validity"""
    return {
        link.link_dir: link
        for link in links
    }

def get_archived_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are archived with a valid data directory"""
    return {
        link.link_dir: link
        for link in filter(is_archived, links)
    }

def get_unarchived_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are unarchived with no data directory or an empty data directory"""
    return {
        link.link_dir: link
        for link in filter(is_unarchived, links)
    }

def get_present_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that actually exist in the archive/ folder"""
    all_folders = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            all_folders[entry.path] = link

    return all_folders

def get_valid_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs with a valid index matched to the main index and archived content"""
    return {
        link.link_dir: link
        for link in filter(is_valid, links)
    }

def get_invalid_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that are invalid for any reason: corrupted/duplicate/orphaned/unrecognized"""
    duplicate = get_duplicate_folders(links, out_dir=OUTPUT_DIR)
    orphaned = get_orphaned_folders(links, out_dir=OUTPUT_DIR)
    corrupted = get_corrupted_folders(links, out_dir=OUTPUT_DIR)
    unrecognized = get_unrecognized_folders(links, out_dir=OUTPUT_DIR)
    return {**duplicate, **orphaned, **corrupted, **unrecognized}


def get_duplicate_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that conflict with other directories that have the same link URL or timestamp"""
    links = list(links)
    by_url = {link.url: 0 for link in links}
    by_timestamp = {link.timestamp: 0 for link in links}

    duplicate_folders = {}

    indexed_folders = {link.link_dir for link in links}
    data_folders = (
        entry.path
        for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME))
        if entry.is_dir(follow_symlinks=True) and entry.path not in indexed_folders
    )

    for path in chain(sorted(indexed_folders), sorted(data_folders)):
        link = None
        try:
            link = parse_json_link_details(path)
        except Exception:
            pass

        if link:
            # link folder has same timestamp as different link folder
            by_timestamp[link.timestamp] = by_timestamp.get(link.timestamp, 0) + 1
            if by_timestamp[link.timestamp] > 1:
                duplicate_folders[path] = link

            # link folder has same url as different link folder
            by_url[link.url] = by_url.get(link.url, 0) + 1
            if by_url[link.url] > 1:
                duplicate_folders[path] = link

    return duplicate_folders

def get_orphaned_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that contain a valid index but aren't listed in the main index"""
    links = list(links)
    indexed_folders = {link.link_dir: link for link in links}
    orphaned_folders = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            if link and entry.path not in indexed_folders:
                # folder is a valid link data dir with index details, but it's not in the main index
                orphaned_folders[entry.path] = link

    return orphaned_folders

def get_corrupted_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain a valid index and aren't listed in the main index"""
    return {
        link.link_dir: link
        for link in filter(is_corrupt, links)
    }

def get_unrecognized_folders(links, out_dir: str=OUTPUT_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain recognizable archive data and aren't listed in the main index"""
    by_timestamp = {link.timestamp: 0 for link in links}
    unrecognized_folders: Dict[str, Optional[Link]] = {}

    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            index_exists = os.path.exists(os.path.join(entry.path, 'index.json'))
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except KeyError:
                # Try to fix index
                if index_exists:
                    try:
                        # Last attempt to repair the detail index
                        link_guessed = parse_json_link_details(entry.path, guess=True)
                        write_json_link_details(link_guessed, out_dir=entry.path)
                        link = parse_json_link_details(entry.path)
                    except Exception:
                        pass

            if index_exists and link is None:
                # index exists but it's corrupted or unparseable
                unrecognized_folders[entry.path] = link
            
            elif not index_exists:
                # link details index doesn't exist and the folder isn't in the main index
                timestamp = entry.path.rsplit('/', 1)[-1]
                if timestamp not in by_timestamp:
                    unrecognized_folders[entry.path] = link

    return unrecognized_folders


def is_valid(link: Link) -> bool:
    dir_exists = os.path.exists(link.link_dir)
    index_exists = os.path.exists(os.path.join(link.link_dir, 'index.json'))
    if not dir_exists:
        # unarchived links are not included in the valid list
        return False
    if dir_exists and not index_exists:
        return False
    if dir_exists and index_exists:
        try:
            parsed_link = parse_json_link_details(link.link_dir, guess=True)
            return link.url == parsed_link.url
        except Exception:
            pass
    return False

def is_corrupt(link: Link) -> bool:
    if not os.path.exists(link.link_dir):
        # unarchived links are not considered corrupt
        return False

    if is_valid(link):
        return False

    return True

def is_archived(link: Link) -> bool:
    return is_valid(link) and link.is_archived
    
def is_unarchived(link: Link) -> bool:
    if not os.path.exists(link.link_dir):
        return True
    return not link.is_archived


def fix_invalid_folder_locations(out_dir: str=OUTPUT_DIR) -> Tuple[List[str], List[str]]:
    fixed = []
    cant_fix = []
    for entry in os.scandir(os.path.join(out_dir, ARCHIVE_DIR_NAME)):
        if entry.is_dir(follow_symlinks=True):
            if os.path.exists(os.path.join(entry.path, 'index.json')):
                try:
                    link = parse_json_link_details(entry.path)
                except KeyError:
                    link = None
                if not link:
                    continue

                if not entry.path.endswith(f'/{link.timestamp}'):
                    dest = os.path.join(out_dir, ARCHIVE_DIR_NAME, link.timestamp)
                    if os.path.exists(dest):
                        cant_fix.append(entry.path)
                    else:
                        shutil.move(entry.path, dest)
                        fixed.append(dest)
                        timestamp = entry.path.rsplit('/', 1)[-1]
                        assert link.link_dir == entry.path
                        assert link.timestamp == timestamp
                        write_json_link_details(link, out_dir=entry.path)

    return fixed, cant_fix
