from django.utils.html import format_html

from core.models import Snapshot, EXTRACTORS


def get_icons(snapshot: Snapshot) -> str:
    archive_results = snapshot.archiveresult_set
    link = snapshot.as_link()
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
    exclude = ["favicon"]
    # Missing specific entry for WARC

    for extractor, _ in EXTRACTORS:
        result = archive_results.filter(extractor=extractor, status="succeeded")
        path, exists = link.archive_path, result.exists()
        try:
            if extractor not in exclude:
                output += output_template.format(path, canon[f"{extractor}_path"],
                                                 exists, extractor, icons.get(extractor, "?"))
            if extractor == "wget":
                # warc isn't technically it's own extractor, so we have to add it after wget

                output += output_template.format(path, canon["warc_path"],
                                                 exists, "warc", icons.get("warc", "?"))

        except Exception as e:
            print(e)

    return format_html(f'<span class="files-icons" style="font-size: 1.2em; opacity: 0.8">{output}<span>')

#def get_icons(snapshot: Snapshot) -> str:
#    link = snapshot.as_link()
#    canon = link.canonical_outputs()
#    out_dir = Path(link.link_dir)
#
#    # slow version: highlights icons based on whether files exist or not for that output
#    # link_tuple = lambda link, method: (link.archive_path, canon[method] or '', canon[method] and (out_dir / (canon[method] or 'notdone')).exists())
#    # fast version: all icons are highlighted without checking for outputs in filesystem
#    link_tuple = lambda link, method: (link.archive_path, canon[method] or '', canon[method] and (out_dir / (canon[method] or 'notdone')).exists())
#
#    return format_html(
#            '<span class="files-icons" style="font-size: 1.2em; opacity: 0.8">'
#                '<a href="/{}/{}" class="exists-{}" title="SingleFile">❶ </a>'
#                '<a href="/{}/{}" class="exists-{}" title="Wget clone">🆆 </a> '
#                '<a href="/{}/{}" class="exists-{}" title="HTML dump">🅷 </a> '
#                '<a href="/{}/{}" class="exists-{}" title="PDF">📄 </a> '
#                '<a href="/{}/{}" class="exists-{}" title="Screenshot">💻 </a> '
#                '<a href="/{}/{}" class="exists-{}" title="WARC">📦 </a> '
#                '<a href="/{}/{}/" class="exists-{}" title="Media files">📼 </a> '
#                '<a href="/{}/{}/" class="exists-{}" title="Git repos">🅶 </a> '
#                '<a href="{}" class="exists-{}" title="Archive.org snapshot">🏛 </a> '
#            '</span>',
#            *link_tuple(link, 'singlefile_path'),
#            *link_tuple(link, 'wget_path')[:2], any((out_dir / link.domain).glob('*')),
#            *link_tuple(link, 'pdf_path'),
#            *link_tuple(link, 'screenshot_path'),
#            *link_tuple(link, 'dom_path'),
#            *link_tuple(link, 'warc_path')[:2], any((out_dir / canon['warc_path']).glob('*.warc.gz')),
#            *link_tuple(link, 'media_path')[:2], any((out_dir / canon['media_path']).glob('*')),
#            *link_tuple(link, 'git_path')[:2], any((out_dir / canon['git_path']).glob('*')),
#            canon['archive_org_path'], (out_dir / 'archive.org.txt').exists(),
#        )
#
