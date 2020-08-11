__package__ = 'archivebox.index'

import os

from string import Template
from datetime import datetime
from typing import List, Optional, Iterator, Mapping

from .schema import Link
from ..system import atomic_write, copy_and_overwrite
from ..util import (
    enforce_types,
    ts_to_date,
    urlencode,
    htmlencode,
    urldecode,
)
from ..config import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
    VERSION,
    GIT_SHA,
    FOOTER_INFO,
    ARCHIVE_DIR_NAME,
    HTML_INDEX_FILENAME,
    STATIC_DIR_NAME,
    ROBOTS_TXT_FILENAME,
    FAVICON_FILENAME,
)

join = lambda *paths: os.path.join(*paths)
MAIN_INDEX_TEMPLATE = join(TEMPLATES_DIR, 'main_index.html')
MAIN_INDEX_ROW_TEMPLATE = join(TEMPLATES_DIR, 'main_index_row.html')
LINK_DETAILS_TEMPLATE = join(TEMPLATES_DIR, 'link_details.html')
TITLE_LOADING_MSG = 'Not yet archived...'


### Main Links Index

@enforce_types
def parse_html_main_index(out_dir: str=OUTPUT_DIR) -> Iterator[str]:
    """parse an archive index html file and return the list of urls"""

    index_path = join(out_dir, HTML_INDEX_FILENAME)
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            for line in f:
                if 'class="link-url"' in line:
                    yield line.split('"')[1]
    return ()

@enforce_types
def write_html_main_index(links: List[Link], out_dir: str=OUTPUT_DIR, finished: bool=False) -> None:
    """write the html link index to a given path"""

    copy_and_overwrite(join(TEMPLATES_DIR, FAVICON_FILENAME), join(out_dir, FAVICON_FILENAME))
    copy_and_overwrite(join(TEMPLATES_DIR, ROBOTS_TXT_FILENAME), join(out_dir, ROBOTS_TXT_FILENAME))
    copy_and_overwrite(join(TEMPLATES_DIR, STATIC_DIR_NAME), join(out_dir, STATIC_DIR_NAME))
    
    rendered_html = main_index_template(links, finished=finished)
    atomic_write(join(out_dir, HTML_INDEX_FILENAME), rendered_html)


@enforce_types
def main_index_template(links: List[Link], finished: bool=True) -> str:
    """render the template for the entire main index"""

    return render_legacy_template(MAIN_INDEX_TEMPLATE, {
        'version': VERSION,
        'git_sha': GIT_SHA,
        'num_links': str(len(links)),
        'status': 'finished' if finished else 'running',
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'rows': '\n'.join(
            main_index_row_template(link)
            for link in links
        ),
        'footer_info': FOOTER_INFO,
    })


@enforce_types
def main_index_row_template(link: Link) -> str:
    """render the template for an individual link row of the main index"""

    from ..extractors.wget import wget_output_path

    return render_legacy_template(MAIN_INDEX_ROW_TEMPLATE, {
        **link._asdict(extended=True),
        
        # before pages are finished archiving, show loading msg instead of title
        'title': htmlencode(
            link.title
            or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
        ),

        # before pages are finished archiving, show fallback loading favicon
        'favicon_url': (
            join(ARCHIVE_DIR_NAME, link.timestamp, 'favicon.ico')
            # if link['is_archived'] else 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='
        ),

        # before pages are finished archiving, show the details page instead
        'wget_url': urlencode(wget_output_path(link) or 'index.html'),
        
        # replace commas in tags with spaces, or file extension if it's static
        'tags': (link.tags or '') + (' {}'.format(link.extension) if link.is_static else ''),
    })


### Link Details Index

@enforce_types
def write_html_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    out_dir = out_dir or link.link_dir

    rendered_html = link_details_template(link)
    atomic_write(join(out_dir, HTML_INDEX_FILENAME), rendered_html)


@enforce_types
def link_details_template(link: Link) -> str:

    from ..extractors.wget import wget_output_path

    link_info = link._asdict(extended=True)

    return render_legacy_template(LINK_DETAILS_TEMPLATE, {
        **link_info,
        **link_info['canonical'],
        'title': htmlencode(
            link.title
            or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
        ),
        'url_str': htmlencode(urldecode(link.base_url)),
        'archive_url': urlencode(
            wget_output_path(link)
            or (link.domain if link.is_archived else '')
        ) or 'about:blank',
        'extension': link.extension or 'html',
        'tags': link.tags or 'untagged',
        'status': 'archived' if link.is_archived else 'not yet archived',
        'status_color': 'success' if link.is_archived else 'danger',
        'oldest_archive_date': ts_to_date(link.oldest_archive_date),
    })


@enforce_types
def render_legacy_template(template_path: str, context: Mapping[str, str]) -> str:
    """render a given html template string with the given template content"""

    # will be replaced by django templates in the future
    with open(template_path, 'r', encoding='utf-8') as template:
        template_str = template.read()
    return Template(template_str).substitute(**context)
