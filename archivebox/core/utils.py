from django.utils.html import format_html
from collections import defaultdict

from core.models import Snapshot, EXTRACTORS
from pathlib import Path


def get_icons(snapshot: Snapshot) -> str:
    archive_results = snapshot.archiveresult_set.filter(status="succeeded")
    link = snapshot.as_link()
    path = link.archive_path
    canon = link.canonical_outputs()
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
            if exists:
                output += output_template.format(exists[0], "", str(bool(exists)), "warc", icons.get("warc", "?"))

        if extractor == "archive_org":
            # The check for archive_org is different, so it has to be handled separately
            target_path = Path(path) / "archive.org.txt"
            exists = target_path.exists()
            output += '<a href="{}" class="exists-{}" title="{}">{} </a>'.format(canon["archive_org_path"], str(exists),
                                                                                        "archive_org", icons.get("archive_org", "?"))

    return format_html(f'<span class="files-icons" style="font-size: 1.2em; opacity: 0.8">{output}<span>')
