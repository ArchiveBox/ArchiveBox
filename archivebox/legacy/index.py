import os
import json

from datetime import datetime
from string import Template
from typing import List, Tuple, Iterator, Optional, Mapping, Iterable
from collections import OrderedDict

from .schema import Link, ArchiveResult
from .config import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
    VERSION,
    GIT_SHA,
    FOOTER_INFO,
    TIMEOUT,
    URL_BLACKLIST_PTN,
    ANSI,
    stderr,
)
from .util import (
    scheme,
    fuzzy_url,
    ts_to_date,
    urlencode,
    htmlencode,
    urldecode,
    wget_output_path,
    enforce_types,
    TimedProgress,
    copy_and_overwrite,
    atomic_write,
    ExtendedEncoder,
)
from .parse import parse_links
from .logs import (
    log_indexing_process_started,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_started,
    log_parsing_finished,
)

TITLE_LOADING_MSG = 'Not yet archived...'



### Link filtering and checking

@enforce_types
def derived_link_info(link: Link) -> dict:
    """extend link info with the archive urls and other derived data"""

    info = link._asdict(extended=True)
    info.update(link.canonical_outputs())

    return info


@enforce_types
def merge_links(a: Link, b: Link) -> Link:
    """deterministially merge two links, favoring longer field values over shorter,
    and "cleaner" values over worse ones.
    """
    assert a.base_url == b.base_url, 'Cannot merge two links with different URLs'

    url = a.url if len(a.url) > len(b.url) else b.url

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

    timestamp = (
        a.timestamp
        if float(a.timestamp or 0) < float(b.timestamp or 0) else
        b.timestamp
    )

    tags_set = (
        set(tag.strip() for tag in (a.tags or '').split(','))
        | set(tag.strip() for tag in (b.tags or '').split(','))
    )
    tags = ','.join(tags_set) or None

    sources = list(set(a.sources + b.sources))

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

def validate_links(links: Iterable[Link]) -> Iterable[Link]:
    links = archivable_links(links)  # remove chrome://, about:, mailto: etc.
    links = sorted_links(links)      # deterministically sort the links based on timstamp, url
    links = uniquefied_links(links)  # merge/dedupe duplicate timestamps & urls

    if not links:
        print('[X] No links found :(')
        raise SystemExit(1)

    return links

def archivable_links(links: Iterable[Link]) -> Iterable[Link]:
    """remove chrome://, about:// or other schemed links that cant be archived"""
    for link in links:
        scheme_is_valid = scheme(link.url) in ('http', 'https', 'ftp')
        not_blacklisted = (not URL_BLACKLIST_PTN.match(link.url)) if URL_BLACKLIST_PTN else True
        if scheme_is_valid and not_blacklisted:
            yield link


def uniquefied_links(sorted_links: Iterable[Link]) -> Iterable[Link]:
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    """

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
    sort_func = lambda link: (link.timestamp.split('.', 1)[0], link.url)
    return sorted(links, key=sort_func, reverse=True)


def links_after_timestamp(links: Iterable[Link], resume: float=None) -> Iterable[Link]:
    if not resume:
        yield from links
        return

    for link in links:
        try:
            if float(link.timestamp) <= resume:
                yield link
        except (ValueError, TypeError):
            print('Resume value and all timestamp values must be valid numbers.')


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



### Homepage index for all the links

@enforce_types
def write_links_index(links: List[Link], out_dir: str=OUTPUT_DIR, finished: bool=False) -> None:
    """create index.html file for a given list of links"""

    log_indexing_process_started()

    log_indexing_started(out_dir, 'index.json')
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    try:
        write_json_links_index(links, out_dir=out_dir)
    finally:
        timer.end()
    log_indexing_finished(out_dir, 'index.json')
    
    log_indexing_started(out_dir, 'index.html')
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    try:
        write_html_links_index(links, out_dir=out_dir, finished=finished)
    finally:
        timer.end()
    log_indexing_finished(out_dir, 'index.html')


@enforce_types
def load_links_index(out_dir: str=OUTPUT_DIR, import_path: Optional[str]=None) -> Tuple[List[Link], List[Link]]:
    """parse and load existing index with any new links from import_path merged in"""

    existing_links: List[Link] = []
    if out_dir:
        existing_links = list(parse_json_links_index(out_dir))

    new_links: List[Link] = []
    if import_path:
        # parse and validate the import file
        log_parsing_started(import_path)
        raw_links, parser_name = parse_links(import_path)
        new_links = list(validate_links(raw_links))

    # merge existing links in out_dir and new links
    all_links = list(validate_links(existing_links + new_links))

    if import_path and parser_name:
        num_parsed = len(raw_links)
        num_new_links = len(all_links) - len(existing_links)
        log_parsing_finished(num_parsed, num_new_links, parser_name)

    return all_links, new_links


@enforce_types
def write_json_links_index(links: List[Link], out_dir: str=OUTPUT_DIR) -> None:
    """write the json link index to a given path"""

    assert isinstance(links, List), 'Links must be a list, not a generator.'
    assert not links or isinstance(links[0].history, dict)
    assert not links or isinstance(links[0].sources, list)

    if links and links[0].history.get('title'):
        assert isinstance(links[0].history['title'][0], ArchiveResult)

    if links and links[0].sources:
        assert isinstance(links[0].sources[0], str)

    path = os.path.join(out_dir, 'index.json')

    index_json = {
        'info': 'ArchiveBox Index',
        'source': 'https://github.com/pirate/ArchiveBox',
        'docs': 'https://github.com/pirate/ArchiveBox/wiki',
        'version': VERSION,
        'num_links': len(links),
        'updated': datetime.now(),
        'links': links,
    }
    atomic_write(index_json, path)


@enforce_types
def parse_json_links_index(out_dir: str=OUTPUT_DIR) -> Iterator[Link]:
    """parse a archive index json file and return the list of links"""

    index_path = os.path.join(out_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            links = json.load(f)['links']
            for link_json in links:
                yield Link.from_json(link_json)

    return ()


@enforce_types
def write_html_links_index(links: List[Link], out_dir: str=OUTPUT_DIR, finished: bool=False) -> None:
    """write the html link index to a given path"""

    copy_and_overwrite(
        os.path.join(TEMPLATES_DIR, 'static'),
        os.path.join(out_dir, 'static'),
    )

    atomic_write('User-agent: *\nDisallow: /', os.path.join(out_dir, 'robots.txt'))

    with open(os.path.join(TEMPLATES_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        index_html = f.read()

    with open(os.path.join(TEMPLATES_DIR, 'index_row.html'), 'r', encoding='utf-8') as f:
        link_row_html = f.read()

    link_rows = []
    for link in links:
        template_row_vars: Mapping[str, str] = {
            **derived_link_info(link),
            'title': (
                link.title
                or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
            ),
            'tags': (link.tags or '') + (' {}'.format(link.extension) if link.is_static else ''),
            'favicon_url': (
                os.path.join('archive', link.timestamp, 'favicon.ico')
                # if link['is_archived'] else 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='
            ),
            'archive_url': urlencode(
                wget_output_path(link) or 'index.html'
            ),
        }
        link_rows.append(Template(link_row_html).substitute(**template_row_vars))

    template_vars: Mapping[str, str] = {
        'num_links': str(len(links)),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'footer_info': FOOTER_INFO,
        'version': VERSION,
        'git_sha': GIT_SHA,
        'rows': '\n'.join(link_rows),
        'status': 'finished' if finished else 'running',
    }
    template_html = Template(index_html).substitute(**template_vars)

    atomic_write(template_html, os.path.join(out_dir, 'index.html'))



@enforce_types
def patch_links_index(link: Link, out_dir: str=OUTPUT_DIR) -> None:
    """hack to in-place update one row's info in the generated index html"""

    title = link.title or link.latest_outputs()['title']
    successful = link.num_outputs

    # Patch JSON index
    json_file_links = parse_json_links_index(out_dir)
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
    
    write_json_links_index(patched_links, out_dir=out_dir)

    # Patch HTML index
    html_path = os.path.join(out_dir, 'index.html')
    html = open(html_path, 'r').read().split('\n')
    for idx, line in enumerate(html):
        if title and ('<span data-title-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(title)
        elif successful and ('<span data-number-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(successful)
            break

    atomic_write('\n'.join(html), html_path)


### Individual link index

@enforce_types
def write_link_index(link: Link, link_dir: Optional[str]=None) -> None:
    link_dir = link_dir or link.link_dir

    write_json_link_index(link, link_dir)
    write_html_link_index(link, link_dir)


@enforce_types
def write_json_link_index(link: Link, link_dir: Optional[str]=None) -> None:
    """write a json file with some info about the link"""
    
    link_dir = link_dir or link.link_dir
    path = os.path.join(link_dir, 'index.json')

    atomic_write(link._asdict(), path)


@enforce_types
def parse_json_link_index(link_dir: str) -> Optional[Link]:
    """load the json link index from a given directory"""
    existing_index = os.path.join(link_dir, 'index.json')
    if os.path.exists(existing_index):
        with open(existing_index, 'r', encoding='utf-8') as f:
            link_json = json.load(f)
            return Link.from_json(link_json)
    return None


@enforce_types
def load_json_link_index(link: Link, link_dir: Optional[str]=None) -> Link:
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    link_dir = link_dir or link.link_dir
    existing_link = parse_json_link_index(link_dir)
    if existing_link:
        return merge_links(existing_link, link)
    return link


@enforce_types
def write_html_link_index(link: Link, link_dir: Optional[str]=None) -> None:
    link_dir = link_dir or link.link_dir

    with open(os.path.join(TEMPLATES_DIR, 'link_index.html'), 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(link_dir, 'index.html')

    template_vars: Mapping[str, str] = {
        **derived_link_info(link),
        'title': (
            link.title
            or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
        ),
        'url_str': htmlencode(urldecode(link.base_url)),
        'archive_url': urlencode(
            wget_output_path(link)
            or (link.domain if link.is_archived else 'about:blank')
        ),
        'extension': link.extension or 'html',
        'tags': link.tags or 'untagged',
        'status': 'archived' if link.is_archived else 'not yet archived',
        'status_color': 'success' if link.is_archived else 'danger',
        'oldest_archive_date': ts_to_date(link.oldest_archive_date),
    }

    html_index = Template(link_html).substitute(**template_vars)

    atomic_write(html_index, path)
