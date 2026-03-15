
__package__ = 'archivebox.core'

import os
from pathlib import Path

from django.contrib import admin, messages
from django.urls import path
from django.utils.html import format_html, mark_safe
from django.utils import timezone
from django.db.models import Q, Sum, Count, Prefetch
from django.db.models.functions import Coalesce
from django import forms
from django.template import Template, RequestContext
from django.contrib.admin.helpers import ActionForm

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.util import htmldecode, urldecode
from archivebox.misc.paginators import AccelleratedPaginator
from archivebox.misc.logging_util import printable_filesize
from archivebox.search.admin import SearchResultsAdminMixin
from archivebox.core.host_utils import build_snapshot_url, build_web_url

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.workers.tasks import bg_archive_snapshots, bg_add

from archivebox.core.models import Tag, Snapshot, ArchiveResult
from archivebox.core.admin_archiveresults import ArchiveResultInline, render_archiveresults_list
from archivebox.core.widgets import TagEditorWidget, InlineTagEditorWidget


# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': [], 'CAN_UPGRADE': False}
GLOBAL_CONTEXT = {}


class SnapshotActionForm(ActionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define tags field in __init__ to avoid database access during app initialization
        self.fields['tags'] = forms.CharField(
            label='',
            required=False,
            widget=TagEditorWidget(),
        )

    def clean_tags(self):
        """Parse comma-separated tag names into Tag objects."""
        tags_str = self.cleaned_data.get('tags', '')
        if not tags_str:
            return []

        tag_names = [name.strip() for name in tags_str.split(',') if name.strip()]
        tags = []
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(
                name__iexact=name,
                defaults={'name': name}
            )
            # Use the existing tag if found by case-insensitive match
            tag = Tag.objects.filter(name__iexact=name).first() or tag
            tags.append(tag)
        return tags

    # TODO: allow selecting actions for specific extractor plugins? is this useful?
    # plugin = forms.ChoiceField(
    #     choices=ArchiveResult.PLUGIN_CHOICES,
    #     required=False,
    #     widget=forms.MultileChoiceField(attrs={'class': "form-control"})
    # )


class TagNameListFilter(admin.SimpleListFilter):
    title = 'By tag name'
    parameter_name = 'tag'

    def lookups(self, request, model_admin):
        return [(str(tag.pk), tag.name) for tag in Tag.objects.order_by('name')]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(tags__id=self.value())
        return queryset


class SnapshotAdminForm(forms.ModelForm):
    """Custom form for Snapshot admin with tag editor widget."""
    tags_editor = forms.CharField(
        label='Tags',
        required=False,
        widget=TagEditorWidget(),
        help_text='Type tag names and press Enter or Space to add. Click × to remove.',
    )

    class Meta:
        model = Snapshot
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize tags_editor with current tags
        if self.instance and self.instance.pk:
            self.initial['tags_editor'] = ','.join(
                sorted(tag.name for tag in self.instance.tags.all())
            )

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Handle tags_editor field
        if commit:
            instance.save()
            self._save_m2m()

            # Parse and save tags from tags_editor
            tags_str = self.cleaned_data.get('tags_editor', '')
            if tags_str:
                tag_names = [name.strip() for name in tags_str.split(',') if name.strip()]
                tags = []
                for name in tag_names:
                    tag, _ = Tag.objects.get_or_create(
                        name__iexact=name,
                        defaults={'name': name}
                    )
                    tag = Tag.objects.filter(name__iexact=name).first() or tag
                    tags.append(tag)
                instance.tags.set(tags)
            else:
                instance.tags.clear()

        return instance


class SnapshotAdmin(SearchResultsAdminMixin, ConfigEditorMixin, BaseModelAdmin):
    form = SnapshotAdminForm
    list_display = ('created_at', 'preview_icon', 'title_str', 'tags_inline', 'status_with_progress', 'files', 'size_with_stats')
    sort_fields = ('title_str', 'created_at', 'status', 'crawl')
    readonly_fields = ('admin_actions', 'status_info', 'imported_timestamp', 'created_at', 'modified_at', 'downloaded_at', 'output_dir', 'archiveresults_list')
    search_fields = ('id', 'url', 'timestamp', 'title', 'tags__name')
    list_filter = ('created_at', 'downloaded_at', 'archiveresult__status', 'crawl__created_by', TagNameListFilter)

    fieldsets = (
        ('Actions', {
            'fields': ('admin_actions',),
            'classes': ('card', 'wide', 'actions-card'),
        }),
        ('URL', {
            'fields': ('url', 'title'),
            'classes': ('card', 'wide'),
        }),
        ('Tags', {
            'fields': ('tags_editor',),
            'classes': ('card',),
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
            'fields': ('crawl',),
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
        ('Archive Results', {
            'fields': ('archiveresults_list',),
            'classes': ('card', 'wide'),
        }),
    )

    ordering = ['-created_at']
    actions = ['add_tags', 'remove_tags', 'resnapshot_snapshot', 'update_snapshots', 'overwrite_snapshots', 'delete_snapshots']
    inlines = []  # Removed TagInline, using TagEditorWidget instead
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

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            func, name, _desc = actions['delete_selected']
            actions['delete_selected'] = (func, name, 'Delete')
        return actions


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
    def get_queryset(self, request):
        self.request = request
        ordering_fields = self._get_ordering_fields(request)
        needs_size_sort = 'size_with_stats' in ordering_fields
        needs_files_sort = 'files' in ordering_fields
        needs_tags_sort = 'tags_inline' in ordering_fields

        prefetch_qs = ArchiveResult.objects.filter(
            Q(status='succeeded')
        ).only(
            'id',
            'snapshot_id',
            'plugin',
            'status',
            'output_size',
            'output_files',
            'output_str',
        )

        qs = (
            super()
            .get_queryset(request)
            .defer('config', 'notes')
            .prefetch_related('tags')
            .prefetch_related(Prefetch('archiveresult_set', queryset=prefetch_qs))
        )

        if needs_size_sort:
            qs = qs.annotate(
                output_size_sum=Coalesce(Sum(
                    'archiveresult__output_size',
                    filter=Q(archiveresult__status='succeeded'),
                ), 0),
            )

        if needs_files_sort:
            qs = qs.annotate(
                ar_succeeded_count=Count(
                    'archiveresult',
                    filter=Q(archiveresult__status='succeeded'),
                ),
            )
        if needs_tags_sort:
            qs = qs.annotate(tag_count=Count('tags', distinct=True))

        return qs

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

    @admin.display(description='')
    def admin_actions(self, obj):
        summary_url = build_web_url(f'/{obj.archive_path}')
        results_url = build_web_url(f'/{obj.archive_path}/index.html#all')
        return format_html(
            '''
            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📄 View Snapshot
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📁 All files
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   target="_blank"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    🔗 Original URL
                </a>

                <span style="border-left: 1px solid #e2e8f0; height: 24px; margin: 0 4px;"></span>

                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1e40af; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Create a fresh new snapshot of this URL"
                   onmouseover="this.style.background='#dbeafe';"
                   onmouseout="this.style.background='#eff6ff';">
                    🆕 Archive Now
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; color: #065f46; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Redo failed extractors (missing outputs)"
                   onmouseover="this.style.background='#d1fae5';"
                   onmouseout="this.style.background='#ecfdf5';">
                    🔁 Redo Failed
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
            summary_url,
            results_url,
            obj.url,
            obj.pk,
            obj.pk,
            obj.pk,
            obj.pk,
        )

    def status_info(self, obj):
        favicon_url = build_snapshot_url(str(obj.id), 'favicon.ico')
        return format_html(
            '''
            Archived: {} ({} files {}) &nbsp; &nbsp;
            Favicon: <img src="{}" style="height: 20px"/> &nbsp; &nbsp;
            Extension: {} &nbsp; &nbsp;
            ''',
            '✅' if obj.is_archived else '❌',
            obj.num_outputs,
            self.size(obj) or '0kb',
            favicon_url,
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
        title_raw = (obj.title or '').strip()
        url_raw = (obj.url or '').strip()
        title_normalized = title_raw.lower()
        url_normalized = url_raw.lower()
        show_title = bool(title_raw) and title_normalized != 'pending...' and title_normalized != url_normalized
        css_class = 'fetched' if show_title else 'pending'

        detail_url = build_web_url(f'/{obj.archive_path}/index.html')
        title_html = ''
        if show_title:
            title_html = format_html(
                '<a href="{}">'
                    '<b class="status-{}">{}</b>'
                '</a>',
                detail_url,
                css_class,
                urldecode(htmldecode(title_raw))[:128],
            )

        return format_html(
            '{}'
            '<div style="font-size: 11px; color: #64748b; margin-top: 2px;">'
                '<a href="{}"><code style="user-select: all;">{}</code></a>'
            '</div>',
            title_html,
            url_raw or obj.url,
            (url_raw or obj.url)[:128],
        )

    @admin.display(description='Tags', ordering='tag_count')
    def tags_inline(self, obj):
        widget = InlineTagEditorWidget(snapshot_id=str(obj.pk))
        tags_html = widget.render(
            name=f'tags_{obj.pk}',
            value=obj.tags.all(),
            attrs={'id': f'tags_{obj.pk}'},
            snapshot_id=str(obj.pk),
        )
        return mark_safe(f'<span class="tags-inline-editor">{tags_html}</span>')

    @admin.display(description='Preview', empty_value='')
    def preview_icon(self, obj):
        results = self._get_prefetched_results(obj)
        has_screenshot = False
        has_favicon = False
        if results is not None:
            has_screenshot = any(r.plugin == 'screenshot' for r in results)
            has_favicon = any(r.plugin == 'favicon' for r in results)

        if not has_screenshot and not has_favicon:
            return None

        if has_screenshot:
            img_url = build_snapshot_url(str(obj.id), 'screenshot/screenshot.png')
            fallbacks = [
                build_snapshot_url(str(obj.id), 'screenshot.png'),
                build_snapshot_url(str(obj.id), 'favicon/favicon.ico'),
                build_snapshot_url(str(obj.id), 'favicon.ico'),
            ]
            img_alt = 'Screenshot'
            preview_class = 'screenshot'
        else:
            img_url = build_snapshot_url(str(obj.id), 'favicon/favicon.ico')
            fallbacks = [
                build_snapshot_url(str(obj.id), 'favicon.ico'),
            ]
            img_alt = 'Favicon'
            preview_class = 'favicon'

        fallback_list = ','.join(fallbacks)
        onerror_js = (
            "this.dataset.fallbacks && this.dataset.fallbacks.length ? "
            "(this.src=this.dataset.fallbacks.split(',').shift(), "
            "this.dataset.fallbacks=this.dataset.fallbacks.split(',').slice(1).join(',')) : "
            "this.remove()"
        )

        return format_html(
            '<img src="{}" alt="{}" class="snapshot-preview {}" decoding="async" loading="lazy" '
            'onerror="{}" data-fallbacks="{}">',
            img_url,
            img_alt,
            preview_class,
            onerror_js,
            fallback_list,
        )

    @admin.display(
        description='Files Saved',
        ordering='ar_succeeded_count',
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
            '<a href="{}" title="View all files">{}</a>',
            build_web_url(f'/{obj.archive_path}'),
            size_txt,
        )

    @admin.display(
        description='Status',
        ordering='status',
    )
    def status_with_progress(self, obj):
        """Show status with progress bar for in-progress snapshots."""
        stats = self._get_progress_stats(obj)

        # Status badge colors
        status_colors = {
            'queued': ('#f59e0b', '#fef3c7'),      # amber
            'started': ('#3b82f6', '#dbeafe'),     # blue
            'sealed': ('#10b981', '#d1fae5'),      # green
            'succeeded': ('#10b981', '#d1fae5'),   # green
            'failed': ('#ef4444', '#fee2e2'),      # red
            'backoff': ('#f59e0b', '#fef3c7'),     # amber
            'skipped': ('#6b7280', '#f3f4f6'),     # gray
        }
        fg_color, bg_color = status_colors.get(obj.status, ('#6b7280', '#f3f4f6'))

        # For started snapshots, show progress bar
        if obj.status == 'started' and stats['total'] > 0:
            percent = stats['percent']
            running = stats['running']
            succeeded = stats['succeeded']
            failed = stats['failed']

            return format_html(
                '''<div style="min-width: 120px;">
                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                        <span class="snapshot-progress-spinner"></span>
                        <span style="font-size: 11px; color: #64748b;">{}/{} hooks</span>
                    </div>
                    <div style="background: #e2e8f0; border-radius: 4px; height: 6px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #10b981 0%, #10b981 {}%, #ef4444 {}%, #ef4444 {}%, #3b82f6 {}%, #3b82f6 100%);
                                    width: {}%; height: 100%; transition: width 0.3s;"></div>
                    </div>
                    <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">
                        ✓{} ✗{} ⏳{}
                    </div>
                </div>''',
                succeeded + failed + stats['skipped'],
                stats['total'],
                int(succeeded / stats['total'] * 100) if stats['total'] else 0,
                int(succeeded / stats['total'] * 100) if stats['total'] else 0,
                int((succeeded + failed) / stats['total'] * 100) if stats['total'] else 0,
                int((succeeded + failed) / stats['total'] * 100) if stats['total'] else 0,
                percent,
                succeeded,
                failed,
                running,
            )

        # For other statuses, show simple badge
        return format_html(
            '<span style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 500; background: {}; color: {};">{}</span>',
            bg_color,
            fg_color,
            obj.status.upper(),
        )

    @admin.display(
        description='Size',
        ordering='output_size_sum',
    )
    def size_with_stats(self, obj):
        """Show archive size with output size from archive results."""
        stats = self._get_progress_stats(obj)
        output_size = stats['output_size']
        size_bytes = output_size or 0

        if size_bytes:
            size_txt = printable_filesize(size_bytes)
            if size_bytes > 52428800:  # 50MB
                size_txt = mark_safe(f'<b>{size_txt}</b>')
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')

        # Show hook statistics
        if stats['total'] > 0:
            return format_html(
                '<a href="{}" title="View all files" style="white-space: nowrap;">'
                '{}</a>'
                '<div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">'
                '{}/{} hooks</div>',
                build_web_url(f'/{obj.archive_path}'),
                size_txt,
                stats['succeeded'],
                stats['total'],
            )

        return format_html(
            '<a href="{}" title="View all files">{}</a>',
            build_web_url(f'/{obj.archive_path}'),
            size_txt,
        )

    def _get_progress_stats(self, obj):
        results = self._get_prefetched_results(obj)
        if results is None:
            return obj.get_progress_stats()

        total = len(results)
        succeeded = sum(1 for r in results if r.status == 'succeeded')
        failed = sum(1 for r in results if r.status == 'failed')
        running = sum(1 for r in results if r.status == 'started')
        skipped = sum(1 for r in results if r.status == 'skipped')
        pending = max(total - succeeded - failed - running - skipped, 0)
        completed = succeeded + failed + skipped
        percent = int((completed / total * 100) if total > 0 else 0)
        is_sealed = obj.status not in (obj.StatusChoices.QUEUED, obj.StatusChoices.STARTED)
        output_size = None

        if hasattr(obj, 'output_size_sum'):
            output_size = obj.output_size_sum or 0
        else:
            output_size = sum(r.output_size or 0 for r in results if r.status == 'succeeded')

        return {
            'total': total,
            'succeeded': succeeded,
            'failed': failed,
            'running': running,
            'pending': pending,
            'skipped': skipped,
            'percent': percent,
            'output_size': output_size or 0,
            'is_sealed': is_sealed,
        }

    def _get_prefetched_results(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'archiveresult_set' in obj._prefetched_objects_cache:
            return obj.archiveresult_set.all()
        return None

    def _get_ordering_fields(self, request):
        ordering = request.GET.get('o')
        if not ordering:
            return set()
        fields = set()
        for part in ordering.split('.'):
            if not part:
                continue
            try:
                idx = abs(int(part)) - 1
            except ValueError:
                continue
            if 0 <= idx < len(self.list_display):
                fields.add(self.list_display[idx])
        return fields

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

    @admin.display(description='Health', ordering='health')
    def health_display(self, obj):
        h = obj.health
        color = 'green' if h >= 80 else 'orange' if h >= 50 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, h)

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
        description="🔁 Redo Failed"
    )
    def update_snapshots(self, request, queryset):
        count = queryset.count()

        queued = bg_archive_snapshots(queryset, kwargs={"overwrite": False, "out_dir": DATA_DIR})

        messages.success(
            request,
            f"Queued {queued} snapshots for re-archiving. The orchestrator will process them in the background.",
        )


    @admin.action(
        description="🆕 Archive Now"
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
        description="🗑️ Delete"
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
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get('tags', '')
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        # Parse comma-separated tag names and get/create Tag objects
        tag_names = [name.strip() for name in tags_str.split(',') if name.strip()]
        tags = []
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(
                name__iexact=name,
                defaults={'name': name}
            )
            tag = Tag.objects.filter(name__iexact=name).first() or tag
            tags.append(tag)

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list('id', flat=True))
        num_snapshots = len(snapshot_ids)

        print('[+] Adding tags', [t.name for t in tags], 'to', num_snapshots, 'Snapshots')

        # Bulk create M2M relationships (1 query per tag, not per snapshot)
        for tag in tags:
            SnapshotTag.objects.bulk_create(
                [SnapshotTag(snapshot_id=sid, tag=tag) for sid in snapshot_ids],
                ignore_conflicts=True  # Skip if relationship already exists
            )

        messages.success(
            request,
            f"Added {len(tags)} tag(s) to {num_snapshots} Snapshot(s).",
        )


    @admin.action(
        description="–"
    )
    def remove_tags(self, request, queryset):
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get('tags', '')
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        # Parse comma-separated tag names and find matching Tag objects (case-insensitive)
        tag_names = [name.strip() for name in tags_str.split(',') if name.strip()]
        tags = []
        for name in tag_names:
            tag = Tag.objects.filter(name__iexact=name).first()
            if tag:
                tags.append(tag)

        if not tags:
            messages.warning(request, "No matching tags found.")
            return

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list('id', flat=True))
        num_snapshots = len(snapshot_ids)
        tag_ids = [t.pk for t in tags]

        print('[-] Removing tags', [t.name for t in tags], 'from', num_snapshots, 'Snapshots')

        # Bulk delete M2M relationships (1 query total, not per snapshot)
        deleted_count, _ = SnapshotTag.objects.filter(
            snapshot_id__in=snapshot_ids,
            tag_id__in=tag_ids
        ).delete()

        messages.success(
            request,
            f"Removed {len(tags)} tag(s) from {num_snapshots} Snapshot(s) ({deleted_count} associations deleted).",
        )
