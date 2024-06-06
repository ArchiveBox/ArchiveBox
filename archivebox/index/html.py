__package__ = 'archivebox.index'

from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Optional, Iterator, Mapping

from django.utils.html import format_html, mark_safe
from django.core.cache import cache

from .schema import Link
from ..system import atomic_write
from ..logging_util import printable_filesize
from ..util import (
    enforce_types,
    ts_to_date_str,
    urlencode,
    htmlencode,
    urldecode,
)
from ..config import (
    OUTPUT_DIR,
    VERSION,
    FOOTER_INFO,
    HTML_INDEX_FILENAME,
    SAVE_ARCHIVE_DOT_ORG,
    PREVIEW_ORIGINALS,
)

MAIN_INDEX_TEMPLATE = 'static_index.html'
MINIMAL_INDEX_TEMPLATE = 'minimal_index.html'
LINK_DETAILS_TEMPLATE = 'snapshot.html'
TITLE_LOADING_MSG = 'Not yet archived...'


### Main Links Index

@enforce_types
def parse_html_main_index(out_dir: Path=OUTPUT_DIR) -> Iterator[str]:
    """parse an archive index html file and return the list of urls"""

    index_path = Path(out_dir) / HTML_INDEX_FILENAME
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            for line in f:
                if 'class="link-url"' in line:
                    yield line.split('"')[1]
    return ()

@enforce_types
def generate_index_from_links(links: List[Link], with_headers: bool):
    if with_headers:
        output = main_index_template(links)
    else:
        output = main_index_template(links, template=MINIMAL_INDEX_TEMPLATE)
    return output

@enforce_types
def main_index_template(links: List[Link], template: str=MAIN_INDEX_TEMPLATE) -> str:
    """render the template for the entire main index"""

    return render_django_template(template, {
        'version': VERSION,
        'git_sha': VERSION,  # not used anymore, but kept for backwards compatibility
        'num_links': str(len(links)),
        'date_updated': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'time_updated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
        'links': [link._asdict(extended=True) for link in links],
        'FOOTER_INFO': FOOTER_INFO,
    })


### Link Details Index

@enforce_types
def write_html_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    out_dir = out_dir or link.link_dir

    rendered_html = link_details_template(link)
    atomic_write(str(Path(out_dir) / HTML_INDEX_FILENAME), rendered_html)


@enforce_types
def link_details_template(link: Link) -> str:

    from ..extractors.wget import wget_output_path

    link_info = link._asdict(extended=True)

    return render_django_template(LINK_DETAILS_TEMPLATE, {
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
        'size': printable_filesize(link.archive_size) if link.archive_size else 'pending',
        'status': 'archived' if link.is_archived else 'not yet archived',
        'status_color': 'success' if link.is_archived else 'danger',
        'oldest_archive_date': ts_to_date_str(link.oldest_archive_date),
        'SAVE_ARCHIVE_DOT_ORG': SAVE_ARCHIVE_DOT_ORG,
        'PREVIEW_ORIGINALS': PREVIEW_ORIGINALS,
    })

@enforce_types
def render_django_template(template: str, context: Mapping[str, str]) -> str:
    """render a given html template string with the given template content"""
    from django.template.loader import render_to_string

    return render_to_string(template, context)


def snapshot_icons(snapshot) -> str:
    cache_key = f'{snapshot.id}-{(snapshot.updated or snapshot.added).timestamp()}-snapshot-icons'
    
    def calc_snapshot_icons():
        from core.models import EXTRACTORS
        # start = datetime.now(timezone.utc)

        archive_results = snapshot.archiveresult_set.filter(status="succeeded", output__isnull=False)
        link = snapshot.as_link()
        path = link.archive_path
        canon = link.canonical_outputs()
        output = ""
        output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{}</a> &nbsp;'
        icons = {
            "singlefile": "❶",
            "wget": "🆆",
            "dom": "🅷",
            "pdf": "📄",
            "screenshot": "💻",
            "media": "📼",
            "git": "🅶",
            "archive_org": "🏛",
            "readability": "🆁",
            "mercury": "🅼",
            "warc": "📦",
            "papers": "🔬"
        }
        exclude = ["favicon", "title", "headers", "htmltotext", "archive_org"]
        # Missing specific entry for WARC

        extractor_outputs = defaultdict(lambda: None)
        for extractor, _ in EXTRACTORS:
            for result in archive_results:
                if result.extractor == extractor and result:
                    extractor_outputs[extractor] = result

        for extractor, _ in EXTRACTORS:
            if extractor not in exclude:
                existing = extractor_outputs[extractor] and extractor_outputs[extractor].status == 'succeeded' and extractor_outputs[extractor].output
                # Check filesystsem to see if anything is actually present (too slow, needs optimization/caching)
                # if existing:
                #     existing = (Path(path) / existing)
                #     if existing.is_file():
                #         existing = True
                #     elif existing.is_dir():
                #         existing = any(existing.glob('*.*'))
                output += format_html(output_template, path, canon[f"{extractor}_path"], str(bool(existing)),
                                             extractor, icons.get(extractor, "?"))
            if extractor == "wget":
                # warc isn't technically it's own extractor, so we have to add it after wget
                
                # get from db (faster but less thurthful)
                exists = extractor_outputs[extractor] and extractor_outputs[extractor].status == 'succeeded' and extractor_outputs[extractor].output
                # get from filesystem (slower but more accurate)
                # exists = list((Path(path) / canon["warc_path"]).glob("*.warc.gz"))
                output += format_html(output_template, path, canon["warc_path"], str(bool(exists)), "warc", icons.get("warc", "?"))

            if extractor == "archive_org":
                # The check for archive_org is different, so it has to be handled separately

                # get from db (faster)
                exists = extractor in extractor_outputs and extractor_outputs[extractor] and extractor_outputs[extractor].status == 'succeeded' and extractor_outputs[extractor].output
                # get from filesystem (slower)
                # target_path = Path(path) / "archive.org.txt"
                # exists = target_path.exists()
                output += '<a href="{}" class="exists-{}" title="{}">{}</a> '.format(canon["archive_org_path"], str(exists),
                                                                                            "archive_org", icons.get("archive_org", "?"))

        result = format_html('<span class="files-icons" style="font-size: 1.1em; opacity: 0.8; min-width: 240px; display: inline-block">{}<span>', mark_safe(output))
        # end = datetime.now(timezone.utc)
        # print(((end - start).total_seconds()*1000) // 1, 'ms')
        return result

    return cache.get_or_set(cache_key, calc_snapshot_icons)
    # return calc_snapshot_icons()

   
