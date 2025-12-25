
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

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.workers.tasks import bg_archive_snapshots, bg_add

from core.models import Tag, Snapshot
from core.admin_tags import TagInline
from core.admin_archiveresults import ArchiveResultInline, render_archiveresults_list


# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': [], 'CAN_UPGRADE': False}
GLOBAL_CONTEXT = {}


class SnapshotActionForm(ActionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define tags field in __init__ to avoid database access during app initialization
        self.fields['tags'] = forms.ModelMultipleChoiceField(
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


class SnapshotAdmin(SearchResultsAdminMixin, ConfigEditorMixin, BaseModelAdmin):
    list_display = ('created_at', 'title_str', 'status', 'files', 'size', 'url_str')
    sort_fields = ('title_str', 'url_str', 'created_at', 'status', 'crawl')
    readonly_fields = ('admin_actions', 'status_info', 'tags_str', 'imported_timestamp', 'created_at', 'modified_at', 'downloaded_at', 'output_dir', 'archiveresults_list')
    search_fields = ('id', 'url', 'timestamp', 'title', 'tags__name')
    list_filter = ('created_at', 'downloaded_at', 'archiveresult__status', 'created_by', 'tags__name')

    fieldsets = (
        ('URL', {
            'fields': ('url', 'title'),
            'classes': ('card', 'wide'),
        }),
        ('Status', {
            'fields': ('status', 'retry_at', 'status_info'),
            'classes': ('card',),
        }),
        ('Timestamps', {
            'fields': ('bookmarked_at', 'created_at', 'modified_at', 'downloaded_at'),
            'classes': ('card',),
        }),
        ('Relations', {
            'fields': ('crawl', 'created_by', 'tags_str'),
            'classes': ('card',),
        }),
        ('Config', {
            'fields': ('config',),
            'classes': ('card',),
        }),
        ('Files', {
            'fields': ('output_dir',),
            'classes': ('card',),
        }),
        ('Actions', {
            'fields': ('admin_actions',),
            'classes': ('card', 'wide'),
        }),
        ('Archive Results', {
            'fields': ('archiveresults_list',),
            'classes': ('card', 'wide'),
        }),
    )

    ordering = ['-created_at']
    actions = ['add_tags', 'remove_tags', 'update_titles', 'update_snapshots', 'resnapshot_snapshot', 'overwrite_snapshots', 'delete_snapshots']
    inlines = [TagInline]  # Removed ArchiveResultInline, using custom renderer instead
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

    @admin.display(description="Imported Timestamp")
    def imported_timestamp(self, obj):
        context = RequestContext(self.request, {
            'bookmarked_date': obj.bookmarked_at,
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
            '''
            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/archive/{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📄 Summary Page
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/archive/{}/index.html#all"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📁 Result Files
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   target="_blank"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    🔗 Original URL
                </a>

                <span style="border-left: 1px solid #e2e8f0; height: 24px; margin: 0 4px;"></span>

                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; color: #065f46; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Get missing extractors"
                   onmouseover="this.style.background='#d1fae5';"
                   onmouseout="this.style.background='#ecfdf5';">
                    ⬇️ Get Missing
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1e40af; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Create a fresh new snapshot of this URL"
                   onmouseover="this.style.background='#dbeafe';"
                   onmouseout="this.style.background='#eff6ff';">
                    🆕 Archive Again
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; color: #92400e; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Re-run all extractors (overwrite existing)"
                   onmouseover="this.style.background='#fef3c7';"
                   onmouseout="this.style.background='#fffbeb';">
                    🔄 Redo All
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; color: #991b1b; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Permanently delete this snapshot"
                   onmouseover="this.style.background='#fee2e2';"
                   onmouseout="this.style.background='#fef2f2';">
                    ☠️ Delete
                </a>
            </div>
            <p style="margin-top: 12px; font-size: 12px; color: #64748b;">
                <b>Tip:</b> Action buttons link to the list view with this snapshot pre-selected. Select it and use the action dropdown to execute.
            </p>
            ''',
            obj.timestamp,
            obj.timestamp,
            obj.url,
            obj.pk,
            obj.pk,
            obj.pk,
            obj.pk,
        )

    def status_info(self, obj):
        return format_html(
            '''
            Archived: {} ({} files {}) &nbsp; &nbsp;
            Favicon: <img src="{}" style="height: 20px"/> &nbsp; &nbsp;
            Extension: {} &nbsp; &nbsp;
            ''',
            '✅' if obj.is_archived else '❌',
            obj.num_outputs,
            self.size(obj) or '0kb',
            f'/archive/{obj.timestamp}/favicon.ico',
            obj.extension or '-',
        )

    @admin.display(description='Archive Results')
    def archiveresults_list(self, obj):
        return render_archiveresults_list(obj.archiveresult_set.all())

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
        # Show title if available, otherwise show URL
        display_text = obj.title or obj.url
        css_class = 'fetched' if obj.title else 'pending'

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
            css_class,
            urldecode(htmldecode(display_text))[:128]
        ) + mark_safe(f' <span class="tags">{tags}</span>')

    @admin.display(
        description='Files Saved',
        # ordering='archiveresult_count',
    )
    def files(self, obj):
        # return '-'
        return obj.icons()


    @admin.display(
        # ordering='archiveresult_count'
    )
    def size(self, obj):
        archive_size = os.access(Path(obj.output_dir) / 'index.html', os.F_OK) and obj.archive_size
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
        count = queryset.count()

        # Queue snapshots for archiving via the state machine system
        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": True, "methods": ["title", "favicon"], "out_dir": DATA_DIR})
        messages.success(
            request,
            f"Queued {queued} snapshots for title/favicon update. The orchestrator will process them in the background.",
        )

    @admin.action(
        description="⬇️ Get Missing"
    )
    def update_snapshots(self, request, queryset):
        count = queryset.count()

        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": False, "out_dir": DATA_DIR})

        messages.success(
            request,
            f"Queued {queued} snapshots for re-archiving. The orchestrator will process them in the background.",
        )


    @admin.action(
        description="🆕 Archive Again"
    )
    def resnapshot_snapshot(self, request, queryset):
        for snapshot in queryset:
            timestamp = timezone.now().isoformat('T', 'seconds')
            new_url = snapshot.url.split('#')[0] + f'#{timestamp}'

            bg_add({'urls': new_url, 'tag': snapshot.tags_str()})

        messages.success(
            request,
            f"Creating {queryset.count()} new fresh snapshots. The orchestrator will process them in the background.",
        )

    @admin.action(
        description="🔄 Redo"
    )
    def overwrite_snapshots(self, request, queryset):
        count = queryset.count()

        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": True, "out_dir": DATA_DIR})

        messages.success(
            request,
            f"Queued {queued} snapshots for full re-archive (overwriting existing). The orchestrator will process them in the background.",
        )

    @admin.action(
        description="☠️ Delete"
    )
    def delete_snapshots(self, request, queryset):
        """Delete snapshots in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list('pk', flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Snapshot.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(
            request,
            mark_safe(f"Successfully deleted {total} Snapshots ({deleted_count} total objects including related records). Don't forget to scrub URLs from import logs (data/sources) and error logs (data/logs) if needed."),
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
