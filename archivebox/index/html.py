__package__ = 'archivebox.index'

from datetime import datetime
from typing import List, Optional, Iterator, Mapping
from pathlib import Path

from django.utils.html import format_html
from django.db.models import Model
from collections import defaultdict

from .schema import Link
from ..system import atomic_write
from ..logging_util import printable_filesize
from ..util import (
    enforce_types,
    ts_to_date,
    urlencode,
    htmlencode,
    urldecode,
)
from ..config import (
    OUTPUT_DIR,
    VERSION,
    GIT_SHA,
    FOOTER_INFO,
    HTML_INDEX_FILENAME,
)

MAIN_INDEX_TEMPLATE = 'main_index.html'
MINIMAL_INDEX_TEMPLATE = 'main_index_minimal.html'
LINK_DETAILS_TEMPLATE = 'link_details.html'
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
def generate_index_from_snapshots(snapshots: List[Model], with_headers: bool):
    if with_headers:
        output = main_index_template(snapshots)
    else:
        output = main_index_template(snapshots, template=MINIMAL_INDEX_TEMPLATE)
    return output

@enforce_types
def main_index_template(snapshots: List[Model], template: str=MAIN_INDEX_TEMPLATE) -> str:
    """render the template for the entire main index"""

    return render_django_template(template, {
        'version': VERSION,
        'git_sha': GIT_SHA,
        'num_snapshots': str(len(snapshots)),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'snapshots': snapshots,
        'FOOTER_INFO': FOOTER_INFO,
    })


### Link Details Index

@enforce_types
def write_html_snapshot_details(snapshot: Model, out_dir: Optional[str]=None) -> None:
    out_dir = out_dir or snapshot.snapshot_dir

    rendered_html = link_details_template(link)
    atomic_write(str(Path(out_dir) / HTML_INDEX_FILENAME), rendered_html)


@enforce_types
def link_details_template(snapshot: Model) -> str:

    from ..extractors.wget import wget_output_path

    snapshot._asdict()

    return render_django_template(LINK_DETAILS_TEMPLATE, {
        **snapshot._asdict(),
        **snapshot.canonical_outputs(),
        'title': htmlencode(
            snapshot.title
            or (snapshot.base_url if snapshot.is_archived else TITLE_LOADING_MSG)
        ),
        'url_str': htmlencode(urldecode(snapshot.base_url)),
        'archive_url': urlencode(
            wget_output_path(snapshot)
            or (snapshot.domain if snapshot.is_archived else '')
        ) or 'about:blank',
        'extension': snapshot.extension or 'html',
        'tags': snapshot.tags.all() or 'untagged', #TODO: Return a proper comma separated list. Leaving it like this for now to revisit when fixing tags
        'size': printable_filesize(snapshot.archive_size) if snapshot.archive_size else 'pending',
        'status': 'archived' if snapshot.is_archived else 'not yet archived',
        'status_color': 'success' if snapshot.is_archived else 'danger',
        'oldest_archive_date': ts_to_date(snapshot.oldest_archive_date),
    })

@enforce_types
def render_django_template(template: str, context: Mapping[str, str]) -> str:
    """render a given html template string with the given template content"""
    from django.template.loader import render_to_string

    return render_to_string(template, context)


def snapshot_icons(snapshot) -> str:
    from core.models import EXTRACTORS

    archive_results = snapshot.archiveresult_set.filter(status="succeeded")
    path = snapshot.archive_path
    canon = snapshot.canonical_outputs()
    output = ""
    output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{} </a>'
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
        "warc": "📦"
    }
    exclude = ["favicon", "title", "headers", "archive_org"]
    # Missing specific entry for WARC

    extractor_items = defaultdict(lambda: None)
    for extractor, _ in EXTRACTORS:
        for result in archive_results:
            if result.extractor == extractor:
                extractor_items[extractor] = result

    for extractor, _ in EXTRACTORS:
        if extractor not in exclude:
            exists = extractor_items[extractor] is not None
            output += output_template.format(path, canon[f"{extractor}_path"], str(exists),
                                             extractor, icons.get(extractor, "?"))
        if extractor == "wget":
            # warc isn't technically it's own extractor, so we have to add it after wget
            exists = list((Path(path) / canon["warc_path"]).glob("*.warc.gz"))
            output += output_template.format(exists[0] if exists else '#', canon["warc_path"], str(bool(exists)), "warc", icons.get("warc", "?"))

        if extractor == "archive_org":
            # The check for archive_org is different, so it has to be handled separately
            target_path = Path(path) / "archive.org.txt"
            exists = target_path.exists()
            output += '<a href="{}" class="exists-{}" title="{}">{}</a> '.format(canon["archive_org_path"], str(exists),
                                                                                        "archive_org", icons.get("archive_org", "?"))

    return format_html(f'<span class="files-icons" style="font-size: 1.1em; opacity: 0.8">{output}<span>')
