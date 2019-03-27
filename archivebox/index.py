import os
import json

from datetime import datetime
from string import Template
from typing import List, Tuple, Iterator, Optional
from dataclasses import fields

from schema import Link, ArchiveIndex, ArchiveResult
from config import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
    GIT_SHA,
    FOOTER_INFO,
    TIMEOUT,
)
from util import (
    merge_links,
    chmod_file,
    urlencode,
    derived_link_info,
    wget_output_path,
    ExtendedEncoder,
    enforce_types,
    TimedProgress,
    copy_and_overwrite,
)
from parse import parse_links
from links import validate_links
from logs import (
    log_indexing_process_started,
    log_indexing_started,
    log_indexing_finished,
    log_parsing_started,
    log_parsing_finished,
)

TITLE_LOADING_MSG = 'Not yet archived...'


### Homepage index for all the links

@enforce_types
def write_links_index(out_dir: str, links: List[Link], finished: bool=False) -> None:
    """create index.html file for a given list of links"""

    log_indexing_process_started()

    log_indexing_started(out_dir, 'index.json')
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    write_json_links_index(out_dir, links)
    timer.end()
    log_indexing_finished(out_dir, 'index.json')
    
    log_indexing_started(out_dir, 'index.html')
    timer = TimedProgress(TIMEOUT * 2, prefix='      ')
    write_html_links_index(out_dir, links, finished=finished)
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
def write_json_links_index(out_dir: str, links: List[Link]) -> None:
    """write the json link index to a given path"""

    assert isinstance(links, List), 'Links must be a list, not a generator.'
    assert isinstance(links[0].history, dict)
    assert isinstance(links[0].sources, list)

    if links[0].history.get('title'):
        assert isinstance(links[0].history['title'][0], ArchiveResult)

    if links[0].sources:
        assert isinstance(links[0].sources[0], str)

    path = os.path.join(out_dir, 'index.json')

    index_json = ArchiveIndex(
        info='ArchiveBox Index',
        source='https://github.com/pirate/ArchiveBox',
        docs='https://github.com/pirate/ArchiveBox/wiki',
        version=GIT_SHA,
        num_links=len(links),
        updated=datetime.now(),
        links=links,
    )

    assert isinstance(index_json._asdict(), dict)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index_json._asdict(), f, indent=4, cls=ExtendedEncoder)

    chmod_file(path)


@enforce_types
def parse_json_links_index(out_dir: str=OUTPUT_DIR) -> Iterator[Link]:
    """parse a archive index json file and return the list of links"""

    allowed_fields = {f.name for f in fields(Link)}

    index_path = os.path.join(out_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            links = json.load(f)['links']
            for link_json in links:
                yield Link(**{
                    key: val
                    for key, val in link_json.items()
                    if key in allowed_fields
                })

    return ()


@enforce_types
def write_html_links_index(out_dir: str, links: List[Link], finished: bool=False) -> None:
    """write the html link index to a given path"""

    path = os.path.join(out_dir, 'index.html')

    copy_and_overwrite(os.path.join(TEMPLATES_DIR, 'static'), os.path.join(out_dir, 'static'))

    with open(os.path.join(out_dir, 'robots.txt'), 'w+') as f:
        f.write('User-agent: *\nDisallow: /')

    with open(os.path.join(TEMPLATES_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        index_html = f.read()

    with open(os.path.join(TEMPLATES_DIR, 'index_row.html'), 'r', encoding='utf-8') as f:
        link_row_html = f.read()

    link_rows = '\n'.join(
        Template(link_row_html).substitute(**{
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
        })
        for link in links
    )

    template_vars = {
        'num_links': len(links),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'footer_info': FOOTER_INFO,
        'git_sha': GIT_SHA,
        'short_git_sha': GIT_SHA[:8],
        'rows': link_rows,
        'status': 'finished' if finished else 'running',
    }

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(index_html).substitute(**template_vars))

    chmod_file(path)


@enforce_types
def patch_links_index(link: Link, out_dir: str=OUTPUT_DIR) -> None:
    """hack to in-place update one row's info in the generated index html"""

    title = link.title or link.latest_outputs()['title']
    successful = link.num_outputs

    # Patch JSON index
    changed = False
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
    
    write_json_links_index(out_dir, patched_links)

    # Patch HTML index
    html_path = os.path.join(out_dir, 'index.html')
    html = open(html_path, 'r').read().split('\n')
    for idx, line in enumerate(html):
        if title and ('<span data-title-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(title)
        elif successful and ('<span data-number-for="{}"'.format(link.url) in line):
            html[idx] = '<span>{}</span>'.format(successful)
            break

    with open(html_path, 'w') as f:
        f.write('\n'.join(html))


### Individual link index

@enforce_types
def write_link_index(out_dir: str, link: Link) -> None:
    write_json_link_index(out_dir, link)
    write_html_link_index(out_dir, link)


@enforce_types
def write_json_link_index(out_dir: str, link: Link) -> None:
    """write a json file with some info about the link"""
    
    path = os.path.join(out_dir, 'index.json')

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(link._asdict(), f, indent=4, cls=ExtendedEncoder)

    chmod_file(path)


@enforce_types
def parse_json_link_index(out_dir: str) -> Optional[Link]:
    """load the json link index from a given directory"""
    existing_index = os.path.join(out_dir, 'index.json')
    if os.path.exists(existing_index):
        with open(existing_index, 'r', encoding='utf-8') as f:
            link_json = json.load(f)
            return Link(**link_json)
    return None


@enforce_types
def load_json_link_index(out_dir: str, link: Link) -> Link:
    """check for an existing link archive in the given directory, 
       and load+merge it into the given link dict
    """
    existing_link = parse_json_link_index(out_dir)
    if existing_link:
        return merge_links(existing_link, link)
    return link


@enforce_types
def write_html_link_index(out_dir: str, link: Link) -> None:
    with open(os.path.join(TEMPLATES_DIR, 'link_index.html'), 'r', encoding='utf-8') as f:
        link_html = f.read()

    path = os.path.join(out_dir, 'index.html')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(Template(link_html).substitute({
            **derived_link_info(link),
            'title': (
                link.title
                or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
            ),
            'archive_url': urlencode(
                wget_output_path(link)
                or (link.domain if link.is_archived else 'about:blank')
            ),
            'extension': link.extension or 'html',
            'tags': link.tags or 'untagged',
            'status': 'archived' if link.is_archived else 'not yet archived',
            'status_color': 'success' if link.is_archived else 'danger',
        }))

    chmod_file(path)
