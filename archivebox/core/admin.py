__package__ = 'archivebox.core'

from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

from django.contrib import admin
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model

from core.models import Snapshot
from core.forms import AddLinkForm

from util import htmldecode, urldecode, ansi_to_html
from logging_util import printable_filesize
from main import add, remove
from config import OUTPUT_DIR
from extractors import archive_links

# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel

def update_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], out_dir=OUTPUT_DIR)
update_snapshots.short_description = "Archive"

def update_titles(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, methods=('title',), out_dir=OUTPUT_DIR)
update_titles.short_description = "Pull title"

def overwrite_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, out_dir=OUTPUT_DIR)
overwrite_snapshots.short_description = "Re-archive (overwrite)"

def verify_snapshots(modeladmin, request, queryset):
    for snapshot in queryset:
        print(snapshot.timestamp, snapshot.url, snapshot.is_archived, snapshot.archive_size, len(snapshot.history))

verify_snapshots.short_description = "Check"

def delete_snapshots(modeladmin, request, queryset):
    remove(links=[snapshot.as_link() for snapshot in queryset], yes=True, delete=True, out_dir=OUTPUT_DIR)

delete_snapshots.short_description = "Delete"


class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('added', 'title_str', 'url_str', 'files', 'size')
    sort_fields = ('title_str', 'url_str', 'added')
    readonly_fields = ('id', 'url', 'timestamp', 'num_outputs', 'is_archived', 'url_hash', 'added', 'updated')
    search_fields = ('url', 'timestamp', 'title', 'tags')
    fields = ('title', 'tags', *readonly_fields)
    list_filter = ('added', 'updated', 'tags')
    ordering = ['-added']
    actions = [delete_snapshots, overwrite_snapshots, update_snapshots, update_titles, verify_snapshots]
    actions_template = 'admin/actions_as_select.html'

    def id_str(self, obj):
        return format_html(
            '<code style="font-size: 10px">{}</code>',
            obj.url_hash[:8],
        )

    def title_str(self, obj):
        canon = obj.as_link().canonical_outputs()
        tags = ''.join(
            format_html('<span>{}</span>', tag.strip())
            for tag in obj.tags.split(',')
        ) if obj.tags else ''
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
            urldecode(htmldecode(obj.latest_title or obj.title or ''))[:128] or 'Pending...'
        ) + mark_safe(f'<span class="tags">{tags}</span>')

    def files(self, obj):
        link = obj.as_link()
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
            path('core/snapshot/add/', self.add_view, name='Add'),
        ] + super().get_urls()

    def add_view(self, request):
        if not request.user.is_authenticated:
            return redirect(f'/admin/login/?next={request.path}')

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
admin.site.disable_action('delete_selected')
