__package__ = 'archivebox.core'

from io import StringIO
from contextlib import redirect_stdout

from django.contrib import admin
from django.urls import path
from django.utils.html import format_html
from django.shortcuts import render
from django.contrib.auth import get_user_model

from core.models import Snapshot
from core.forms import AddLinkForm

from ..util import htmldecode, urldecode, ansi_to_html
from ..logging_util import printable_filesize
from ..main import add
from ..config import OUTPUT_DIR

# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel


class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('added', 'title_str', 'url_str', 'tags', 'files', 'size', 'updated')
    sort_fields = ('title_str', 'url_str', 'tags', 'added', 'updated')
    readonly_fields = ('id', 'url', 'timestamp', 'num_outputs', 'is_archived', 'url_hash', 'added', 'updated')
    search_fields = ('url', 'timestamp', 'title', 'tags')
    fields = ('title', 'tags', *readonly_fields)
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
                '<img src="/{}/{}" class="favicon" onerror="this.remove()">'
            '</a>'
            '<a href="/{}/{}">'
                '<b class="status-{}">{}</b>'
            '</a>',
            obj.archive_path,
            obj.archive_path, canon['favicon_path'],
            obj.archive_path, canon['wget_path'] or '',
            'fetched' if obj.latest_title or obj.title else 'pending',
            urldecode(htmldecode(obj.latest_title or obj.title or ''))[:128] or 'Pending...',
        )

    def files(self, obj):
        canon = obj.as_link().canonical_outputs()
        return format_html(
            '<span style="font-size: 1.2em; opacity: 0.8">'
                '<a href="/{}/{}" title="Wget clone">🌐 </a> '
                '<a href="/{}/{}" title="PDF">📄</a> '
                '<a href="/{}/{}" title="Screenshot">🖥 </a> '
                '<a href="/{}/{}" title="HTML dump">🅷 </a> '
                '<a href="/{}/{}" title="Media files">📼 </a> '
                '<a href="/{}/{}" title="Git repos">📦 </a> '
                '<a href="/{}/{}" title="Archive.org snapshot">🏛 </a> '
            '</span>',
            obj.archive_path, canon['wget_path'] or '',
            obj.archive_path, canon['pdf_path'],
            obj.archive_path, canon['screenshot_path'],
            obj.archive_path, canon['dom_path'],
            obj.archive_path, canon['media_path'],
            obj.archive_path, canon['git_path'],
            obj.archive_path, canon['archive_org_path'],
        )

    def size(self, obj):
        return format_html(
            '<a href="/{}" title="View all files">{}</a>',
            obj.archive_path,
            printable_filesize(obj.archive_size) if obj.archive_size else 'pending',
        )

    def url_str(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            obj.url,
            obj.url.split('://www.', 1)[-1].split('://', 1)[-1][:64],
        )

    id_str.short_description = 'ID'
    title_str.short_description = 'Title'
    url_str.short_description = 'Original URL'

    id_str.admin_order_field = 'id'
    title_str.admin_order_field = 'title'
    url_str.admin_order_field = 'url'



class ArchiveBoxAdmin(admin.AdminSite):
    site_header = 'ArchiveBox'
    index_title = 'Links'
    site_title = 'Index'

    def get_urls(self):
        return [
            path('core/snapshot/add/', self.add_view, name='add'),
        ] + super().get_urls()

    def add_view(self, request):
        request.current_app = self.name
        context = {
            **self.each_context(request),
            'title': 'Add URLs',
        }

        if request.method == 'GET':
            context['form'] = AddLinkForm()

        elif request.method == 'POST':
            form = AddLinkForm(request.POST)
            if form.is_valid():
                url = form.cleaned_data["url"]
                print(f'[+] Adding URL: {url}')
                depth = 0 if form.cleaned_data["depth"] == "0" else 1
                input_kwargs = {
                    "urls": url,
                    "depth": depth,
                    "update_all": False,
                    "out_dir": OUTPUT_DIR,
                }
                add_stdout = StringIO()
                with redirect_stdout(add_stdout):
                   add(**input_kwargs)
                print(add_stdout.getvalue())

                context.update({
                    "stdout": ansi_to_html(add_stdout.getvalue().strip()),
                    "form": AddLinkForm()
                })
            else:
                context["form"] = form

        return render(template_name='add_links.html', request=request, context=context)


admin.site = ArchiveBoxAdmin()
admin.site.register(get_user_model())
admin.site.register(Snapshot, SnapshotAdmin)
