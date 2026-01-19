__package__ = 'archivebox.crawls'

import json
from pathlib import Path

from django import forms
from django.utils.html import format_html, format_html_join, mark_safe
from django.contrib import admin, messages
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Count, Q

from archivebox import DATA_DIR

from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl, CrawlSchedule


def render_snapshots_list(snapshots_qs, limit=20):
    """Render a nice inline list view of snapshots with status, title, URL, and progress."""

    snapshots = snapshots_qs.order_by('-created_at')[:limit].annotate(
        total_results=Count('archiveresult'),
        succeeded_results=Count('archiveresult', filter=Q(archiveresult__status='succeeded')),
        failed_results=Count('archiveresult', filter=Q(archiveresult__status='failed')),
    )

    if not snapshots:
        return mark_safe('<div style="color: #666; font-style: italic; padding: 8px 0;">No Snapshots yet...</div>')

    # Status colors matching Django admin and progress monitor
    status_colors = {
        'queued': ('#6c757d', '#f8f9fa'),      # gray
        'started': ('#856404', '#fff3cd'),     # amber
        'sealed': ('#155724', '#d4edda'),      # green
        'failed': ('#721c24', '#f8d7da'),      # red
    }

    rows = []
    for snapshot in snapshots:
        status = snapshot.status or 'queued'
        color, bg = status_colors.get(status, ('#6c757d', '#f8f9fa'))

        # Calculate progress
        total = snapshot.total_results
        done = snapshot.succeeded_results + snapshot.failed_results
        progress_pct = int((done / total) * 100) if total > 0 else 0
        progress_text = f'{done}/{total}' if total > 0 else '-'

        # Truncate title and URL
        title = (snapshot.title or 'Untitled')[:60]
        if len(snapshot.title or '') > 60:
            title += '...'
        url_display = snapshot.url[:50]
        if len(snapshot.url) > 50:
            url_display += '...'

        # Format date
        date_str = snapshot.created_at.strftime('%Y-%m-%d %H:%M') if snapshot.created_at else '-'

        rows.append(f'''
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 6px 8px; white-space: nowrap;">
                    <span style="display: inline-block; padding: 2px 8px; border-radius: 10px;
                                 font-size: 11px; font-weight: 500; text-transform: uppercase;
                                 color: {color}; background: {bg};">{status}</span>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap;">
                    <a href="/{snapshot.archive_path}/" style="text-decoration: none;">
                        <img src="/{snapshot.archive_path}/favicon.ico"
                             style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px;"
                             onerror="this.style.display='none'"/>
                    </a>
                </td>
                <td style="padding: 6px 8px; max-width: 300px;">
                    <a href="{snapshot.admin_change_url}" style="color: #417690; text-decoration: none; font-weight: 500;"
                       title="{snapshot.title or 'Untitled'}">{title}</a>
                </td>
                <td style="padding: 6px 8px; max-width: 250px;">
                    <a href="{snapshot.url}" target="_blank"
                       style="color: #666; text-decoration: none; font-family: monospace; font-size: 11px;"
                       title="{snapshot.url}">{url_display}</a>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; text-align: center;">
                    <div style="display: inline-flex; align-items: center; gap: 6px;">
                        <div style="width: 60px; height: 6px; background: #eee; border-radius: 3px; overflow: hidden;">
                            <div style="width: {progress_pct}%; height: 100%;
                                        background: {'#28a745' if snapshot.failed_results == 0 else '#ffc107' if snapshot.succeeded_results > 0 else '#dc3545'};
                                        transition: width 0.3s;"></div>
                        </div>
                        <a href="/admin/core/archiveresult/?snapshot__id__exact={snapshot.id}"
                           style="font-size: 11px; color: #417690; min-width: 35px; text-decoration: none;"
                           title="View archive results">{progress_text}</a>
                    </div>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; color: #888; font-size: 11px;">
                    {date_str}
                </td>
            </tr>
        ''')

    total_count = snapshots_qs.count()
    footer = ''
    if total_count > limit:
        footer = f'''
            <tr>
                <td colspan="6" style="padding: 8px; text-align: center; color: #666; font-size: 12px; background: #f8f9fa;">
                    Showing {limit} of {total_count} snapshots
                </td>
            </tr>
        '''

    return mark_safe(f'''
        <div style="border: 1px solid #ddd; border-radius: 6px; overflow: hidden; max-width: 100%;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #f5f5f5; border-bottom: 2px solid #ddd;">
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Status</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333; width: 24px;"></th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Title</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">URL</th>
                        <th style="padding: 8px; text-align: center; font-weight: 600; color: #333;">Progress</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Created</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                    {footer}
                </tbody>
            </table>
        </div>
    ''')


class CrawlAdminForm(forms.ModelForm):
    """Custom form for Crawl admin to render urls field as textarea."""

    class Meta:
        model = Crawl
        fields = '__all__'
        widgets = {
            'urls': forms.Textarea(attrs={
                'rows': 8,
                'style': 'width: 100%; font-family: monospace; font-size: 13px;',
                'placeholder': 'https://example.com\nhttps://example2.com\n# Comments start with #',
            }),
        }


class CrawlAdmin(ConfigEditorMixin, BaseModelAdmin):
    form = CrawlAdminForm
    list_display = ('id', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'urls_preview', 'schedule_str', 'status', 'retry_at', 'health_display', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'schedule_str', 'status', 'retry_at')
    search_fields = ('id', 'created_by__username', 'max_depth', 'label', 'notes', 'schedule_id', 'status', 'urls')

    readonly_fields = ('created_at', 'modified_at', 'snapshots')

    fieldsets = (
        ('URLs', {
            'fields': ('urls',),
            'classes': ('card', 'wide'),
        }),
        ('Info', {
            'fields': ('label', 'notes', 'tags_str'),
            'classes': ('card',),
        }),
        ('Settings', {
            'fields': ('max_depth', 'config'),
            'classes': ('card',),
        }),
        ('Status', {
            'fields': ('status', 'retry_at'),
            'classes': ('card',),
        }),
        ('Relations', {
            'fields': ('schedule', 'created_by'),
            'classes': ('card',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'modified_at'),
            'classes': ('card',),
        }),
        ('Snapshots', {
            'fields': ('snapshots',),
            'classes': ('card', 'wide'),
        }),
    )

    list_filter = ('max_depth', 'schedule', 'created_by', 'status', 'retry_at')
    ordering = ['-created_at', '-retry_at']
    list_per_page = 100
    actions = ["delete_selected_batched"]
    change_actions = ['recrawl']

    def get_queryset(self, request):
        """Optimize queries with select_related and annotations."""
        qs = super().get_queryset(request)
        return qs.select_related('schedule', 'created_by').annotate(
            num_snapshots_cached=Count('snapshot_set')
        )

    @admin.action(description='Delete selected crawls')
    def delete_selected_batched(self, request, queryset):
        """Delete crawls in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list('pk', flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Crawl.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(request, f'Successfully deleted {total} crawls ({deleted_count} total objects including related records).')

    @action(label='Recrawl', description='Create a new crawl with the same settings')
    def recrawl(self, request, obj):
        """Duplicate this crawl as a new crawl with the same URLs and settings."""
        from django.utils import timezone
        from django.shortcuts import redirect

        # Validate URLs (required for crawl to start)
        if not obj.urls:
            messages.error(request, 'Cannot recrawl: original crawl has no URLs.')
            return redirect('admin:crawls_crawl_change', obj.id)

        new_crawl = Crawl.objects.create(
            urls=obj.urls,
            max_depth=obj.max_depth,
            tags_str=obj.tags_str,
            config=obj.config,
            schedule=obj.schedule,
            label=f"{obj.label} (recrawl)" if obj.label else "",
            notes=obj.notes,
            created_by=request.user,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        messages.success(
            request,
            f'Created new crawl {new_crawl.id} with the same settings. '
            f'It will start processing shortly.'
        )

        return redirect('admin:crawls_crawl_change', new_crawl.id)

    def num_snapshots(self, obj):
        # Use cached annotation from get_queryset to avoid N+1
        return getattr(obj, 'num_snapshots_cached', obj.snapshot_set.count())

    def snapshots(self, obj):
        return render_snapshots_list(obj.snapshot_set.all())

    @admin.display(description='Schedule', ordering='schedule')
    def schedule_str(self, obj):
        if not obj.schedule:
            return mark_safe('<i>None</i>')
        return format_html('<a href="{}">{}</a>', obj.schedule.admin_change_url, obj.schedule)

    @admin.display(description='URLs', ordering='urls')
    def urls_preview(self, obj):
        first_url = obj.get_urls_list()[0] if obj.get_urls_list() else ''
        return first_url[:80] + '...' if len(first_url) > 80 else first_url

    @admin.display(description='Health', ordering='health')
    def health_display(self, obj):
        h = obj.health
        color = 'green' if h >= 80 else 'orange' if h >= 50 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, h)

    @admin.display(description='URLs')
    def urls_editor(self, obj):
        """Editor for crawl URLs."""
        widget_id = f'crawl_urls_{obj.pk}'

        # Escape for safe HTML embedding
        escaped_urls = (obj.urls or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

        # Count lines for auto-expand logic
        line_count = len((obj.urls or '').split('\n'))
        uri_rows = min(max(3, line_count), 10)

        html = f'''
        <div id="{widget_id}_container" style="max-width: 900px;">
            <!-- URLs input -->
            <div style="margin-bottom: 12px;">
                <label style="font-weight: bold; display: block; margin-bottom: 4px;">URLs (one per line):</label>
                <textarea id="{widget_id}_urls"
                          style="width: 100%; font-family: monospace; font-size: 13px;
                                 padding: 8px; border: 1px solid #ccc; border-radius: 4px;
                                 resize: vertical;"
                          rows="{uri_rows}"
                          placeholder="https://example.com&#10;https://example2.com&#10;# Comments start with #"
                          readonly>{escaped_urls}</textarea>
                <p style="color: #666; font-size: 12px; margin: 4px 0 0 0;">
                    {line_count} URL{'s' if line_count != 1 else ''} · Note: URLs displayed here for reference only
                </p>
            </div>
        </div>
        '''
        return mark_safe(html)



class CrawlScheduleAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str')
    search_fields = ('id', 'created_by__username', 'label', 'notes', 'schedule_id', 'template_id', 'template__urls')

    readonly_fields = ('created_at', 'modified_at', 'crawls', 'snapshots')

    fieldsets = (
        ('Schedule Info', {
            'fields': ('label', 'notes'),
            'classes': ('card',),
        }),
        ('Configuration', {
            'fields': ('schedule', 'template'),
            'classes': ('card',),
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'modified_at'),
            'classes': ('card',),
        }),
        ('Crawls', {
            'fields': ('crawls',),
            'classes': ('card', 'wide'),
        }),
        ('Snapshots', {
            'fields': ('snapshots',),
            'classes': ('card', 'wide'),
        }),
    )

    list_filter = ('created_by',)
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Template', ordering='template')
    def template_str(self, obj):
        return format_html('<a href="{}">{}</a>', obj.template.admin_change_url, obj.template)

    def num_crawls(self, obj):
        return obj.crawl_set.count()

    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (crawl.admin_change_url, crawl)
            for crawl in obj.crawl_set.all().order_by('-created_at')[:20]
        )) or mark_safe('<i>No Crawls yet...</i>')
    
    def snapshots(self, obj):
        crawl_ids = obj.crawl_set.values_list('pk', flat=True)
        return render_snapshots_list(Snapshot.objects.filter(crawl_id__in=crawl_ids))


def register_admin(admin_site):
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
