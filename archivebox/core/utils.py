from pathlib import Path

from django.utils.html import format_html

from core.models import Snapshot


def get_icons(snapshot: Snapshot) -> str:
    link = snapshot.as_link()
    canon = link.canonical_outputs()
    out_dir = Path(link.link_dir)

    link_tuple = lambda link, method: (link.archive_path, canon[method] or '', canon[method] and (out_dir / (canon[method] or 'notdone')).exists())

    return format_html(
            '<span class="files-icons" style="font-size: 1.2em; opacity: 0.8">'
                '<a href="/{}/{}/" class="exists-{}" title="Wget clone">🌐 </a> '
                '<a href="/{}/{}" class="exists-{}" title="PDF">📄</a> '
                '<a href="/{}/{}" class="exists-{}" title="Screenshot">🖥 </a> '
                '<a href="/{}/{}" class="exists-{}" title="HTML dump">🅷 </a> '
                '<a href="/{}/{}/" class="exists-{}" title="WARC">🆆 </a> '
                '<a href="/{}/{}" class="exists-{}" title="SingleFile">&#128476; </a>'
                '<a href="/{}/{}/" class="exists-{}" title="Media files">📼 </a> '
                '<a href="/{}/{}/" class="exists-{}" title="Git repos">📦 </a> '
                '<a href="{}" class="exists-{}" title="Archive.org snapshot">🏛 </a> '
            '</span>',
            *link_tuple(link, 'wget_path'),
            *link_tuple(link, 'pdf_path'),
            *link_tuple(link, 'screenshot_path'),
            *link_tuple(link, 'dom_path'),
            *link_tuple(link, 'warc_path')[:2], any((out_dir / canon['warc_path']).glob('*.warc.gz')),
            *link_tuple(link, 'singlefile_path'),
            *link_tuple(link, 'media_path')[:2], any((out_dir / canon['media_path']).glob('*')),
            *link_tuple(link, 'git_path')[:2], any((out_dir / canon['git_path']).glob('*')),
            canon['archive_org_path'], (out_dir / 'archive.org.txt').exists(),
        )
