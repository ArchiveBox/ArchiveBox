
__package__ = 'archivebox.core'

import os
from pathlib import Path

from django.contrib import admin, messages
from django.urls import path
from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django import forms
from django.template import Template, RequestContext
from django.contrib.admin.helpers import ActionForm
from django.contrib.admin.widgets import FilteredSelectMultiple

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.util import htmldecode, urldecode
from archivebox.misc.paginators import AccelleratedPaginator
from archivebox.misc.logging_util import printable_filesize
from archivebox.search.admin import SearchResultsAdminMixin
from archivebox.index.html import snapshot_icons
from archivebox.extractors import archive_links

from archivebox.base_models.admin import ABIDModelAdmin
from archivebox.workers.tasks import bg_archive_links, bg_add

from core.models import Tag
from core.admin_tags import TagInline
from core.admin_archiveresults import ArchiveResultInline, result_url


# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': [], 'CAN_UPGRADE': False}
GLOBAL_CONTEXT = {}


class SnapshotActionForm(ActionForm):
    tags = forms.ModelMultipleChoiceField(
        label='Edit tags',
        queryset=Tag.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(
            'core_tag__name',
            False,
        ),
    )

    # TODO: allow selecting actions for specific extractors? is this useful?
    # extractor = forms.ChoiceField(
    #     choices=ArchiveResult.EXTRACTOR_CHOICES,
    #     required=False,
    #     widget=forms.MultileChoiceField(attrs={'class': "form-control"})
    # )


class SnapshotAdmin(SearchResultsAdminMixin, ABIDModelAdmin):
    list_display = ('created_at', 'title_str', 'status', 'files', 'size', 'url_str')
    sort_fields = ('title_str', 'url_str', 'created_at', 'status', 'crawl')
    readonly_fields = ('admin_actions', 'status_info', 'tags_str', 'imported_timestamp', 'created_at', 'modified_at', 'downloaded_at', 'abid_info', 'link_dir')
    search_fields = ('id', 'url', 'abid', 'timestamp', 'title', 'tags__name')
    list_filter = ('created_at', 'downloaded_at', 'archiveresult__status', 'created_by', 'tags__name')
    fields = ('url', 'title', 'created_by', 'bookmarked_at', 'status', 'retry_at', 'crawl', *readonly_fields)
    ordering = ['-created_at']
    actions = ['add_tags', 'remove_tags', 'update_titles', 'update_snapshots', 'resnapshot_snapshot', 'overwrite_snapshots', 'delete_snapshots']
    inlines = [TagInline, ArchiveResultInline]
    list_per_page = min(max(5, SERVER_CONFIG.SNAPSHOTS_PER_PAGE), 5000)

    action_form = SnapshotActionForm
    paginator = AccelleratedPaginator

    save_on_top = True
    show_full_result_count = False

    def changelist_view(self, request, extra_context=None):
        self.request = request
        extra_context = extra_context or {}
        try:
            return super().changelist_view(request, extra_context | GLOBAL_CONTEXT)
        except Exception as e:
            self.message_user(request, f'Error occurred while loading the page: {str(e)} {request.GET} {request.POST}')
            return super().changelist_view(request, GLOBAL_CONTEXT)


    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('grid/', self.admin_site.admin_view(self.grid_view), name='grid')
        ]
        return custom_urls + urls

    # def get_queryset(self, request):
    #     # tags_qs = SnapshotTag.objects.all().select_related('tag')
    #     # prefetch = Prefetch('snapshottag_set', queryset=tags_qs)

    #     self.request = request
    #     return super().get_queryset(request).prefetch_related('archiveresult_set').distinct()  # .annotate(archiveresult_count=Count('archiveresult'))

    @admin.action(
        description="Imported Timestamp"
    )
    def imported_timestamp(self, obj):
        context = RequestContext(self.request, {
            'bookmarked_date': obj.bookmarked,
            'timestamp': obj.timestamp,
        })

        html = Template("""{{bookmarked_date}} (<code>{{timestamp}}</code>)""")
        return mark_safe(html.render(context))
    
        # pretty_time = obj.bookmarked.strftime('%Y-%m-%d %H:%M:%S')
        # return f'{pretty_time} ({obj.timestamp})'

    # TODO: figure out a different way to do this, you cant nest forms so this doenst work
    # def action(self, obj):
    #     # csrfmiddlewaretoken: Wa8UcQ4fD3FJibzxqHN3IYrrjLo4VguWynmbzzcPYoebfVUnDovon7GEMYFRgsh0
    #     # action: update_snapshots
    #     # select_across: 0
    #     # _selected_action: 76d29b26-2a88-439e-877c-a7cca1b72bb3
    #     return format_html(
    #         '''
    #             <form action="/admin/core/snapshot/" method="post" onsubmit="e => e.stopPropagation()">
    #                 <input type="hidden" name="csrfmiddlewaretoken" value="{}">
    #                 <input type="hidden" name="_selected_action" value="{}">
    #                 <button name="update_snapshots">Check</button>
    #                 <button name="update_titles">Pull title + favicon</button>
    #                 <button name="update_snapshots">Update</button>
    #                 <button name="overwrite_snapshots">Re-Archive (overwrite)</button>
    #                 <button name="delete_snapshots">Permanently delete</button>
    #             </form>
    #         ''',
    #         csrf.get_token(self.request),
    #         obj.pk,
    #     )

    def admin_actions(self, obj):
        return format_html(
            # URL Hash: <code style="font-size: 10px; user-select: all">{}</code><br/>
            '''
            <a class="btn" style="font-size: 18px; display: inline-block; border-radius: 10px; border: 3px solid #eee; padding: 4px 8px" href="/archive/{}">Summary page ➡️</a> &nbsp; &nbsp;
            <a class="btn" style="font-size: 18px; display: inline-block; border-radius: 10px; border: 3px solid #eee; padding: 4px 8px" href="/archive/{}/index.html#all">Result files 📑</a> &nbsp; &nbsp;
            <a class="btn" style="font-size: 18px; display: inline-block; border-radius: 10px; border: 3px solid #eee; padding: 4px 8px" href="/admin/core/snapshot/?id__exact={}">Admin actions ⚙️</a>
            ''',
            obj.timestamp,
            obj.timestamp,
            obj.pk,
        )

    def status_info(self, obj):
        return format_html(
            # URL Hash: <code style="font-size: 10px; user-select: all">{}</code><br/>
            '''
            Archived: {} ({} files {}) &nbsp; &nbsp;
            Favicon: <img src="{}" style="height: 20px"/> &nbsp; &nbsp;
            Status code: {} &nbsp; &nbsp;<br/>
            Server: {} &nbsp; &nbsp;
            Content type: {} &nbsp; &nbsp;
            Extension: {} &nbsp; &nbsp;
            ''',
            '✅' if obj.is_archived else '❌',
            obj.num_outputs,
            self.size(obj) or '0kb',
            f'/archive/{obj.timestamp}/favicon.ico',
            obj.status_code or '-',
            obj.headers and obj.headers.get('Server') or '-',
            obj.headers and obj.headers.get('Content-Type') or '-',
            obj.extension or '-',
        )

    @admin.display(
        description='Title',
        ordering='title',
    )
    def title_str(self, obj):
        tags = ''.join(
            format_html('<a href="/admin/core/snapshot/?tags__id__exact={}"><span class="tag">{}</span></a> ', tag.pk, tag.name)
            for tag in obj.tags.all()
            if str(tag.name).strip()
        )
        return format_html(
            '<a href="/{}">'
                '<img src="/{}/favicon.ico" class="favicon" onerror="this.remove()">'
            '</a>'
            '<a href="/{}/index.html">'
                '<b class="status-{}">{}</b>'
            '</a>',
            obj.archive_path,
            obj.archive_path,
            obj.archive_path,
            'fetched' if obj.latest_title or obj.title else 'pending',
            urldecode(htmldecode(obj.latest_title or obj.title or ''))[:128] or 'Pending...'
        ) + mark_safe(f' <span class="tags">{tags}</span>')

    @admin.display(
        description='Files Saved',
        # ordering='archiveresult_count',
    )
    def files(self, obj):
        # return '-'
        return snapshot_icons(obj)


    @admin.display(
        # ordering='archiveresult_count'
    )
    def size(self, obj):
        archive_size = os.access(Path(obj.link_dir) / 'index.html', os.F_OK) and obj.archive_size
        if archive_size:
            size_txt = printable_filesize(archive_size)
            if archive_size > 52428800:
                size_txt = mark_safe(f'<b>{size_txt}</b>')
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')
        return format_html(
            '<a href="/{}" title="View all files">{}</a>',
            obj.archive_path,
            size_txt,
        )


    @admin.display(
        description='Original URL',
        ordering='url',
    )
    def url_str(self, obj):
        return format_html(
            '<a href="{}"><code style="user-select: all;">{}</code></a>',
            obj.url,
            obj.url[:128],
        )

    def grid_view(self, request, extra_context=None):

        # cl = self.get_changelist_instance(request)

        # Save before monkey patching to restore for changelist list view
        saved_change_list_template = self.change_list_template
        saved_list_per_page = self.list_per_page
        saved_list_max_show_all = self.list_max_show_all

        # Monkey patch here plus core_tags.py
        self.change_list_template = 'private_index_grid.html'
        self.list_per_page = SERVER_CONFIG.SNAPSHOTS_PER_PAGE
        self.list_max_show_all = self.list_per_page

        # Call monkey patched view
        rendered_response = self.changelist_view(request, extra_context=extra_context)

        # Restore values
        self.change_list_template = saved_change_list_template
        self.list_per_page = saved_list_per_page
        self.list_max_show_all = saved_list_max_show_all

        return rendered_response

    # for debugging, uncomment this to print all requests:
    # def changelist_view(self, request, extra_context=None):
    #     print('[*] Got request', request.method, request.POST)
    #     return super().changelist_view(request, extra_context=None)

    @admin.action(
        description="ℹ️ Get Title"
    )
    def update_titles(self, request, queryset):
        links = [snapshot.as_link() for snapshot in queryset]
        if len(links) < 3:
            # run syncronously if there are only 1 or 2 links
            archive_links(links, overwrite=True, methods=('title','favicon'), out_dir=DATA_DIR)
            messages.success(request, f"Title and favicon have been fetched and saved for {len(links)} URLs.")
        else:
            # otherwise run in a background worker
            result = bg_archive_links((links,), kwargs={"overwrite": True, "methods": ["title", "favicon"], "out_dir": DATA_DIR})
            messages.success(
                request,
                mark_safe(f"Title and favicon are updating in the background for {len(links)} URLs. {result_url(result)}"),
            )

    @admin.action(
        description="⬇️ Get Missing"
    )
    def update_snapshots(self, request, queryset):
        links = [snapshot.as_link() for snapshot in queryset]

        result = bg_archive_links((links,), kwargs={"overwrite": False, "out_dir": DATA_DIR})

        messages.success(
            request,
            mark_safe(f"Re-trying any previously failed methods for {len(links)} URLs in the background. {result_url(result)}"),
        )


    @admin.action(
        description="🆕 Archive Again"
    )
    def resnapshot_snapshot(self, request, queryset):
        for snapshot in queryset:
            timestamp = timezone.now().isoformat('T', 'seconds')
            new_url = snapshot.url.split('#')[0] + f'#{timestamp}'

            result = bg_add({'urls': new_url, 'tag': snapshot.tags_str()})

        messages.success(
            request,
            mark_safe(f"Creating new fresh snapshots for {queryset.count()} URLs in the background. {result_url(result)}"),
        )

    @admin.action(
        description="🔄 Redo"
    )
    def overwrite_snapshots(self, request, queryset):
        links = [snapshot.as_link() for snapshot in queryset]

        result = bg_archive_links((links,), kwargs={"overwrite": True, "out_dir": DATA_DIR})

        messages.success(
            request,
            mark_safe(f"Clearing all previous results and re-downloading {len(links)} URLs in the background. {result_url(result)}"),
        )

    @admin.action(
        description="☠️ Delete"
    )
    def delete_snapshots(self, request, queryset):
        from archivebox.cli.archivebox_remove import remove
        remove(snapshots=queryset, yes=True, delete=True, out_dir=DATA_DIR)
        
        messages.success(
            request,
            mark_safe(f"Succesfully deleted {queryset.count()} Snapshots. Don't forget to scrub URLs from import logs (data/sources) and error logs (data/logs) if needed."),
        )


    @admin.action(
        description="+"
    )
    def add_tags(self, request, queryset):
        tags = request.POST.getlist('tags')
        print('[+] Adding tags', tags, 'to Snapshots', queryset)
        for obj in queryset:
            obj.tags.add(*tags)
        messages.success(
            request,
            f"Added {len(tags)} tags to {queryset.count()} Snapshots.",
        )


    @admin.action(
        description="–"
    )
    def remove_tags(self, request, queryset):
        tags = request.POST.getlist('tags')
        print('[-] Removing tags', tags, 'to Snapshots', queryset)
        for obj in queryset:
            obj.tags.remove(*tags)
        messages.success(
            request,
            f"Removed {len(tags)} tags from {queryset.count()} Snapshots.",
        )
