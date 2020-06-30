from django.contrib import admin
from django.utils.html import format_html

from core.models import Snapshot
from cli.logging import printable_filesize


# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel


class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('id_str', 'title_str', 'url_str', 'tags', 'files', 'added', 'updated', 'timestamp')
    # sort_fields = ('id_str', 'files', 'url_str', 'title_str', 'tags', 'added', 'updated', 'timestamp')
    readonly_fields = ('id', 'num_outputs', 'is_archived', 'url_hash', 'added', 'updated')
    search_fields = ('url', 'timestamp', 'title', 'tags')
    fields = ('url', 'timestamp', 'title', 'tags', *readonly_fields)
    list_filter = ('added', 'updated', 'tags')
    ordering = ['-added']

    def id_str(self, obj):
        return format_html(
            '<code style="font-size: 10px">{}</code>',
            obj.url_hash[:8],
        )

    def title_str(self, obj):
        canon = obj.as_link().canonical_outputs()
        return format_html(
            '<a href="/{}">'
            '<img src="/{}/{}" style="height: 20px; width: 20px;" onerror="this.style.opacity=0">'
            '</a>'
            '<a href="/{}/{}">'
            ' &nbsp; &nbsp; <b>{}</b></a>',
            obj.archive_path,
            obj.archive_path, canon['favicon_path'],
            obj.archive_path, canon['wget_path'] or '',
            (obj.title or '...')[:128],
        )

    def files(self, obj):
        canon = obj.as_link().canonical_outputs()
        return format_html(
            '<span style="font-size: 1.2em; opacity: 0.8">'
            '<a href="/{}/{}">🌐 </a> '
            '<a href="/{}/{}">📄</a> '
            '<a href="/{}/{}">🖥 </a> '
            '<a href="/{}/{}">🅷 </a> '
            '<a href="/{}/{}">📼 </a> '
            '<a href="/{}/{}">📦 </a> '
            '<a href="/{}/{}">🏛 </a> '
            '</span>'
            '<a href="/{}">{}</a>',
            obj.archive_path, canon['wget_path'] or '',
            obj.archive_path, canon['pdf_path'],
            obj.archive_path, canon['screenshot_path'],
            obj.archive_path, canon['dom_path'],
            obj.archive_path, canon['media_path'],
            obj.archive_path, canon['git_path'],
            obj.archive_path, canon['archive_org_path'],
            obj.archive_path,
            printable_filesize(obj.archive_size),
        )

    def url_str(self, obj):
        return format_html(
            '<a href="{}"><code>{}</code></a>',
            obj.url,
            obj.url.split('://', 1)[-1][:128],
        )

    id_str.short_description = 'ID'
    title_str.short_description = 'Title'
    url_str.short_description = 'URL'

    id_str.admin_order_field = 'id'
    title_str.admin_order_field = 'title'
    url_str.admin_order_field = 'url'

admin.site.register(Snapshot, SnapshotAdmin)
