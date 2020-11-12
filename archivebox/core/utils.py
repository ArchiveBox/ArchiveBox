from django.utils.html import format_html

from core.models import Snapshot, EXTRACTORS
from core.settings import DEBUG
from pathlib import Path


def get_icons(snapshot: Snapshot) -> str:
    archive_results = list(snapshot.archiveresult_set.all())
    link = snapshot.as_link()
    canon = link.canonical_outputs()
    output = ""
    output_template = '<a href="/{}/{}" class="exists-True" title="{}">{} </a>'
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
    exclude = ["favicon", "archive_org"]
    # Missing specific entry for WARC

    for extractor, _ in EXTRACTORS:
        for result in archive_results:
            if result.extractor != extractor or result.status != "succeeded":
                continue
            path = link.archive_path
            try:
                if extractor not in exclude:
                    output += output_template.format(path, canon[f"{extractor}_path"],
                                                     extractor, icons.get(extractor, "?"))
                if extractor == "wget":
                    # warc isn't technically it's own extractor, so we have to add it after wget
                    exists = list((Path(path) / canon["warc_path"]).glob("*.warc.gz"))
                    if exists:
                        output += output_template.format(exists[0], "",
                                                         "warc", icons.get("warc", "?"))

                if extractor == "archive_org":
                    # The check for archive_org is different, so it has to be handled separately
                    target_path = Path(path) / "archive.org.txt"
                    exists = target_path.exists()
                    if exists:
                        output += '<a href="{}" class="exists-True" title="{}">{} </a>'.format(canon["archive_org_path"],
                                                                                               "archive_org", icons.get("archive_org", "?"))

            except Exception as e:
                print(e)

    return format_html(f'<span class="files-icons" style="font-size: 1.2em; opacity: 0.8">{output}<span>')
