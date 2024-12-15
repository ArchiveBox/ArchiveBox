__package__ = 'archivebox.index'

import os
import shutil
from pathlib import Path

from itertools import chain
from typing import List, Tuple, Dict, Optional, Iterable
from collections import OrderedDict
from contextlib import contextmanager
from urllib.parse import urlparse
from django.db.models import QuerySet, Q



from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.config.common import ARCHIVING_CONFIG, STORAGE_CONFIG, SEARCH_BACKEND_CONFIG
from archivebox.misc.util import scheme, enforce_types, ExtendedEncoder
from archivebox.misc.logging import stderr
from archivebox.misc.logging_util import (
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
    write_html_link_details,
)
from .json import (
    pyjson,
    parse_json_link_details, 
    write_json_link_details,
)
from .sql import (
    write_sql_main_index,
    write_sql_link_details,
)


### Link filtering and checking

@enforce_types
def merge_links(a: Link, b: Link) -> Link:
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    assert a.base_url == b.base_url, f'Cannot merge two links with different URLs ({a.base_url} != {b.base_url})'

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
    timer = TimedProgress(ARCHIVING_CONFIG.TIMEOUT * 4)
    try:
        links = archivable_links(links)  # remove chrome://, about:, mailto: etc.
        links = sorted_links(links)      # deterministically sort the links based on timestamp, url
        links = fix_duplicate_links(links)  # merge/dedupe duplicate timestamps & urls
    finally:
        timer.end()

    return list(links)

@enforce_types
def archivable_links(links: Iterable[Link]) -> Iterable[Link]:
    """remove chrome://, about:// or other schemed links that cant be archived"""
    
    for link in links:
        try:
            urlparse(link.url)
        except ValueError:
            continue
        if scheme(link.url) not in ('http', 'https', 'ftp'):
            continue
        if ARCHIVING_CONFIG.URL_DENYLIST_PTN and ARCHIVING_CONFIG.URL_DENYLIST_PTN.search(link.url):
            continue
        if ARCHIVING_CONFIG.URL_ALLOWLIST_PTN and (not ARCHIVING_CONFIG.URL_ALLOWLIST_PTN.search(link.url)):
            continue

        yield link


@enforce_types
def fix_duplicate_links(sorted_links: Iterable[Link]) -> Iterable[Link]:
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    """
    # from core.models import Snapshot

    unique_urls: OrderedDict[str, Link] = OrderedDict()

    for link in sorted_links:
        if link.url in unique_urls:
            # merge with any other links that share the same url
            link = merge_links(unique_urls[link.url], link)
        unique_urls[link.url] = link

    return unique_urls.values()


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
def timed_index_update(out_path: Path):
    log_indexing_started(out_path)
    timer = TimedProgress(ARCHIVING_CONFIG.TIMEOUT * 2, prefix='      ')
    try:
        yield
    finally:
        timer.end()

    assert out_path.exists(), f'Failed to write index file: {out_path}'
    log_indexing_finished(out_path)


@enforce_types
def write_main_index(links: List[Link], out_dir: Path=DATA_DIR, created_by_id: int | None=None) -> None:
    """Writes links to sqlite3 file for a given list of links"""

    log_indexing_process_started(len(links))

    try:
        with timed_index_update(CONSTANTS.DATABASE_FILE):
            write_sql_main_index(links, out_dir=out_dir, created_by_id=created_by_id)
            os.chmod(CONSTANTS.DATABASE_FILE, int(STORAGE_CONFIG.OUTPUT_PERMISSIONS, base=8)) # set here because we don't write it with atomic writes

    except (KeyboardInterrupt, SystemExit):
        stderr('[!] Warning: Still writing index to disk...', color='lightyellow')
        stderr('    Run archivebox init to fix any inconsistencies from an ungraceful exit.')
        with timed_index_update(CONSTANTS.DATABASE_FILE):
            write_sql_main_index(links, out_dir=out_dir, created_by_id=created_by_id)
            os.chmod(CONSTANTS.DATABASE_FILE, int(STORAGE_CONFIG.OUTPUT_PERMISSIONS, base=8)) # set here because we don't write it with atomic writes
        raise SystemExit(0)

    log_indexing_process_finished()

@enforce_types
def load_main_index(out_dir: Path | str=DATA_DIR, warn: bool=True) -> List[Link]:
    """parse and load existing index with any new links from import_path merged in"""
    from core.models import Snapshot
    try:
        return Snapshot.objects.all().only('id')

    except (KeyboardInterrupt, SystemExit):
        raise SystemExit(0)

@enforce_types
def load_main_index_meta(out_dir: Path=DATA_DIR) -> Optional[dict]:
    index_path = out_dir / CONSTANTS.JSON_INDEX_FILENAME
    if os.access(index_path, os.F_OK):
        with open(index_path, 'r', encoding='utf-8') as f:
            meta_dict = pyjson.load(f)
            meta_dict.pop('links')
            return meta_dict

    return None


@enforce_types
def parse_links_from_source(source_path: str, root_url: Optional[str]=None, parser: str="auto") -> List[Link]:

    from ..parsers import parse_links

    new_links: List[Link] = []

    # parse and validate the import file
    raw_links, parser_name = parse_links(source_path, root_url=root_url, parser=parser)
    new_links = validate_links(raw_links)

    if parser_name:
        num_parsed = len(raw_links)
        log_parsing_finished(num_parsed, parser_name)

    return new_links

@enforce_types
def fix_duplicate_links_in_index(snapshots: QuerySet, links: Iterable[Link]) -> Iterable[Link]:
    """
    Given a list of in-memory Links, dedupe and merge them with any conflicting Snapshots in the DB.
    """
    unique_urls: OrderedDict[str, Link] = OrderedDict()

    for link in links:
        index_link = snapshots.filter(url=link.url)
        if index_link:
            link = merge_links(index_link[0].as_link(), link)

        unique_urls[link.url] = link

    return unique_urls.values()

@enforce_types
def dedupe_links(snapshots: QuerySet,
                 new_links: List[Link]) -> List[Link]:
    """
    The validation of links happened at a different stage. This method will
    focus on actual deduplication and timestamp fixing.
    """
    
    # merge existing links in out_dir and new links
    dedup_links = fix_duplicate_links_in_index(snapshots, new_links)

    new_links = [
        link for link in new_links
        if not snapshots.filter(url=link.url).exists()
    ]

    dedup_links_dict = {link.url: link for link in dedup_links}

    # Replace links in new_links with the dedup version
    for i in range(len(new_links)):
        if new_links[i].url in dedup_links_dict.keys():
            new_links[i] = dedup_links_dict[new_links[i].url]
    log_deduping_finished(len(new_links))

    return new_links

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
    'exact': lambda pattern: Q(url=pattern),
    'substring': lambda pattern: Q(url__icontains=pattern),
    'regex': lambda pattern: Q(url__iregex=pattern),
    'domain': lambda pattern: Q(url__istartswith=f"http://{pattern}") | Q(url__istartswith=f"https://{pattern}") | Q(url__istartswith=f"ftp://{pattern}"),
    'tag': lambda pattern: Q(tags__name=pattern),
    'timestamp': lambda pattern: Q(timestamp=pattern),
}

@enforce_types
def q_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='exact') -> QuerySet:
    q_filter = Q()
    for pattern in filter_patterns:
        try:
            q_filter = q_filter | LINK_FILTERS[filter_type](pattern)
        except KeyError:
            stderr()
            stderr(
                f'[X] Got invalid pattern for --filter-type={filter_type}:',
                color='red',
            )
            stderr(f'    {pattern}')
            raise SystemExit(2)
    return snapshots.filter(q_filter)

def search_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='search') -> QuerySet:
    from ..search import query_search_index
    
    if not SEARCH_BACKEND_CONFIG.USE_SEARCHING_BACKEND:
        stderr()
        stderr(
                '[X] The search backend is not enabled, set config.USE_SEARCHING_BACKEND = True',
                color='red',
            )
        raise SystemExit(2)
    from core.models import Snapshot

    qsearch = Snapshot.objects.none()
    for pattern in filter_patterns:
        try:
            qsearch |= query_search_index(pattern)
        except:
            raise SystemExit(2)
    
    return snapshots & qsearch

@enforce_types
def snapshot_filter(snapshots: QuerySet, filter_patterns: List[str], filter_type: str='exact') -> QuerySet:
    if filter_type != 'search':
        return q_filter(snapshots, filter_patterns, filter_type)
    else:
        return search_filter(snapshots, filter_patterns, filter_type)


def get_indexed_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """indexed links without checking archive status or data directory validity"""
    links = (snapshot.as_link() for snapshot in snapshots.iterator(chunk_size=500))
    return {
        link.link_dir: link
        for link in links
    }

def get_archived_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are archived with a valid data directory"""
    links = (snapshot.as_link() for snapshot in snapshots.iterator(chunk_size=500))
    return {
        link.link_dir: link
        for link in filter(is_archived, links)
    }

def get_unarchived_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """indexed links that are unarchived with no data directory or an empty data directory"""
    links = (snapshot.as_link() for snapshot in snapshots.iterator(chunk_size=500))
    return {
        link.link_dir: link
        for link in filter(is_unarchived, links)
    }

def get_present_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that actually exist in the archive/ folder"""

    all_folders = {}

    for entry in (out_dir / CONSTANTS.ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            link = None
            try:
                link = parse_json_link_details(entry.path)
            except Exception:
                pass

            all_folders[entry.name] = link

    return all_folders

def get_valid_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs with a valid index matched to the main index and archived content"""
    links = [snapshot.as_link_with_details() for snapshot in snapshots.iterator(chunk_size=500)]
    return {
        link.link_dir: link
        for link in filter(is_valid, links)
    }

def get_invalid_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that are invalid for any reason: corrupted/duplicate/orphaned/unrecognized"""
    duplicate = get_duplicate_folders(snapshots, out_dir=out_dir)
    orphaned = get_orphaned_folders(snapshots, out_dir=out_dir)
    corrupted = get_corrupted_folders(snapshots, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(snapshots, out_dir=out_dir)
    return {**duplicate, **orphaned, **corrupted, **unrecognized}


def get_duplicate_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that conflict with other directories that have the same link URL or timestamp"""
    by_url = {}
    by_timestamp = {}
    duplicate_folders = {}

    data_folders = (
        str(entry)
        for entry in CONSTANTS.ARCHIVE_DIR.iterdir()
            if entry.is_dir() and not snapshots.filter(timestamp=entry.name).exists()
    )

    for path in chain(snapshots.iterator(chunk_size=500), data_folders):
        link = None
        if type(path) is not str:
            path = path.as_link().link_dir

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

def get_orphaned_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that contain a valid index but aren't listed in the main index"""
    orphaned_folders = {}

    for entry in CONSTANTS.ARCHIVE_DIR.iterdir():
        if entry.is_dir():
            link = None
            try:
                link = parse_json_link_details(str(entry))
            except Exception:
                pass

            if link and not snapshots.filter(timestamp=entry.name).exists():
                # folder is a valid link data dir with index details, but it's not in the main index
                orphaned_folders[str(entry)] = link

    return orphaned_folders

def get_corrupted_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain a valid index and aren't listed in the main index"""
    corrupted = {}
    for snapshot in snapshots.iterator(chunk_size=500):
        link = snapshot.as_link()
        if is_corrupt(link):
            corrupted[link.link_dir] = link
    return corrupted

def get_unrecognized_folders(snapshots, out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    """dirs that don't contain recognizable archive data and aren't listed in the main index"""
    unrecognized_folders: Dict[str, Optional[Link]] = {}

    for entry in (Path(out_dir) / CONSTANTS.ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            index_exists = (entry / "index.json").exists()
            link = None
            try:
                link = parse_json_link_details(str(entry))
            except KeyError:
                # Try to fix index
                if index_exists:
                    try:
                        # Last attempt to repair the detail index
                        link_guessed = parse_json_link_details(str(entry), guess=True)
                        write_json_link_details(link_guessed, out_dir=str(entry))
                        link = parse_json_link_details(str(entry))
                    except Exception:
                        pass

            if index_exists and link is None:
                # index exists but it's corrupted or unparseable
                unrecognized_folders[str(entry)] = link
            
            elif not index_exists:
                # link details index doesn't exist and the folder isn't in the main index
                timestamp = entry.name
                if not snapshots.filter(timestamp=timestamp).exists():
                    unrecognized_folders[str(entry)] = link

    return unrecognized_folders


def is_valid(link: Link) -> bool:
    dir_exists = Path(link.link_dir).exists()
    index_exists = (Path(link.link_dir) / "index.json").exists()
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
    if not Path(link.link_dir).exists():
        # unarchived links are not considered corrupt
        return False

    if is_valid(link):
        return False

    return True

def is_archived(link: Link) -> bool:
    return is_valid(link) and link.is_archived
    
def is_unarchived(link: Link) -> bool:
    if not Path(link.link_dir).exists():
        return True
    return not link.is_archived


def fix_invalid_folder_locations(out_dir: Path=DATA_DIR) -> Tuple[List[str], List[str]]:
    fixed = []
    cant_fix = []
    for entry in os.scandir(out_dir / CONSTANTS.ARCHIVE_DIR_NAME):
        if entry.is_dir(follow_symlinks=True):
            if (Path(entry.path) / 'index.json').exists():
                try:
                    link = parse_json_link_details(entry.path)
                except KeyError:
                    link = None
                if not link:
                    continue

                if not entry.path.endswith(f'/{link.timestamp}'):
                    dest = out_dir /CONSTANTS.ARCHIVE_DIR_NAME / link.timestamp
                    if dest.exists():
                        cant_fix.append(entry.path)
                    else:
                        shutil.move(entry.path, dest)
                        fixed.append(dest)
                        timestamp = entry.path.rsplit('/', 1)[-1]
                        assert link.link_dir == entry.path
                        assert link.timestamp == timestamp
                        write_json_link_details(link, out_dir=entry.path)

    return fixed, cant_fix
