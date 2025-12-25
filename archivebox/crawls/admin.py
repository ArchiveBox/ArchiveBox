__package__ = 'archivebox.crawls'

import json
from pathlib import Path

from django.utils.html import format_html, format_html_join, mark_safe
from django.contrib import admin, messages
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Count, Q

from archivebox import DATA_DIR

from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from core.models import Snapshot
from crawls.models import Seed, Crawl, CrawlSchedule


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
                    <a href="/archive/{snapshot.timestamp}/" style="text-decoration: none;">
                        <img src="/archive/{snapshot.timestamp}/favicon.ico"
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


class SeedAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str')
    search_fields = ('id', 'created_by__username', 'label', 'notes', 'uri', 'extractor', 'tags_str')

    readonly_fields = ('created_at', 'modified_at', 'scheduled_crawls', 'crawls', 'snapshots', 'contents')

    fieldsets = (
        ('Source', {
            'fields': ('uri', 'contents'),
            'classes': ('card', 'wide'),
        }),
        ('Info', {
            'fields': ('label', 'notes', 'tags_str'),
            'classes': ('card',),
        }),
        ('Settings', {
            'fields': ('extractor', 'config'),
            'classes': ('card',),
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'modified_at'),
            'classes': ('card',),
        }),
        ('Crawls', {
            'fields': ('scheduled_crawls', 'crawls'),
            'classes': ('card',),
        }),
        ('Snapshots', {
            'fields': ('snapshots',),
            'classes': ('card',),
        }),
    )

    list_filter = ('extractor', 'created_by')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    def num_crawls(self, obj):
        return obj.crawl_set.count()

    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def scheduled_crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (scheduledcrawl.admin_change_url, scheduledcrawl)
            for scheduledcrawl in  obj.scheduled_crawl_set.all().order_by('-created_at')[:20]
        )) or mark_safe('<i>No Scheduled Crawls yet...</i>')

    def crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (crawl.admin_change_url, crawl)
            for crawl in obj.crawl_set.all().order_by('-created_at')[:20]
        )) or mark_safe('<i>No Crawls yet...</i>')

    def snapshots(self, obj):
        return render_snapshots_list(obj.snapshot_set.all())

    def contents(self, obj):
        source_file = obj.get_file_path()
        if source_file:
            contents = ""
            try:
                contents = source_file.read_text().strip()[:14_000]
            except Exception as e:
                contents = f'Error reading {source_file}: {e}'

            return format_html('<b><code>{}</code>:</b><br/><pre>{}</pre>', source_file, contents)

        return format_html('See URLs here: <a href="{}">{}</a>', obj.uri, obj.uri)




class CrawlAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'seed_str', 'schedule_str', 'status', 'retry_at', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'seed_str', 'schedule_str', 'status', 'retry_at')
    search_fields = ('id', 'created_by__username', 'max_depth', 'label', 'notes', 'seed_id', 'schedule_id', 'status', 'seed__uri')

    readonly_fields = ('created_at', 'modified_at', 'snapshots', 'seed_urls_editor')

    fieldsets = (
        ('URLs', {
            'fields': ('seed_urls_editor',),
            'classes': ('card', 'wide'),
        }),
        ('Info', {
            'fields': ('label', 'notes'),
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
            'fields': ('seed', 'schedule', 'created_by'),
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

    list_filter = ('max_depth', 'seed', 'schedule', 'created_by', 'status', 'retry_at')
    ordering = ['-created_at', '-retry_at']
    list_per_page = 100
    actions = ["delete_selected"]
    change_actions = ['recrawl']

    @action(label='Recrawl', description='Create a new crawl with the same settings')
    def recrawl(self, request, obj):
        """Duplicate this crawl as a new crawl with the same seed and settings."""
        from django.utils import timezone
        from django.shortcuts import redirect

        # Validate seed has a URI (required for crawl to start)
        if not obj.seed:
            messages.error(request, 'Cannot recrawl: original crawl has no seed.')
            return redirect('admin:crawls_crawl_change', obj.id)

        if not obj.seed.uri:
            messages.error(request, 'Cannot recrawl: seed has no URI.')
            return redirect('admin:crawls_crawl_change', obj.id)

        new_crawl = Crawl.objects.create(
            seed=obj.seed,
            urls=obj.urls,
            max_depth=obj.max_depth,
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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/save_seed_contents/',
                 self.admin_site.admin_view(self.save_seed_contents_view),
                 name='crawls_crawl_save_seed_contents'),
        ]
        return custom_urls + urls

    def save_seed_contents_view(self, request, object_id):
        """Handle saving seed file contents via AJAX."""
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

        try:
            crawl = Crawl.objects.get(pk=object_id)
        except Crawl.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Crawl not found'}, status=404)

        source_file = crawl.seed.get_file_path() if crawl.seed else None
        if not source_file:
            return JsonResponse({'success': False, 'error': 'Seed is not a local file'}, status=400)

        try:
            data = json.loads(request.body)
            contents = data.get('contents', '')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

        try:
            # Ensure parent directory exists
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(contents)
            return JsonResponse({'success': True, 'message': f'Saved {len(contents)} bytes to {source_file.name}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def snapshots(self, obj):
        return render_snapshots_list(obj.snapshot_set.all())

    @admin.display(description='Schedule', ordering='schedule')
    def schedule_str(self, obj):
        if not obj.schedule:
            return mark_safe('<i>None</i>')
        return format_html('<a href="{}">{}</a>', obj.schedule.admin_change_url, obj.schedule)

    @admin.display(description='Seed', ordering='seed')
    def seed_str(self, obj):
        if not obj.seed:
            return mark_safe('<i>None</i>')
        return format_html('<a href="{}">{}</a>', obj.seed.admin_change_url, obj.seed)

    @admin.display(description='URLs')
    def seed_urls_editor(self, obj):
        """Combined editor showing seed URL and file contents."""
        widget_id = f'seed_urls_{obj.pk}'

        # Get the seed URI (or use urls field if no seed)
        seed_uri = ''
        if obj.seed and obj.seed.uri:
            seed_uri = obj.seed.uri
        elif obj.urls:
            seed_uri = obj.urls

        # Check if it's a local file we can edit
        source_file = obj.seed.get_file_path() if obj.seed else None
        is_file = source_file is not None
        contents = ""
        error = None

        if is_file and source_file:
            try:
                contents = source_file.read_text().strip()
            except Exception as e:
                error = f'Error reading {source_file}: {e}'

        # Escape for safe HTML embedding
        escaped_uri = seed_uri.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        escaped_contents = (contents or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

        # Count lines for auto-expand logic
        line_count = len(contents.split('\n')) if contents else 0
        uri_rows = min(max(1, seed_uri.count('\n') + 1), 3)

        html = f'''
        <div id="{widget_id}_container" style="max-width: 900px;">
            <!-- Seed URL input (auto-expands) -->
            <div style="margin-bottom: 12px;">
                <label style="font-weight: bold; display: block; margin-bottom: 4px;">Seed URL:</label>
                <textarea id="{widget_id}_uri"
                          style="width: 100%; font-family: monospace; font-size: 13px;
                                 padding: 8px; border: 1px solid #ccc; border-radius: 4px;
                                 resize: vertical; min-height: 32px; overflow: hidden;"
                          rows="{uri_rows}"
                          placeholder="file:///data/sources/... or https://..."
                          {"readonly" if not obj.pk else ""}>{escaped_uri}</textarea>
            </div>

            {"" if not is_file else f'''
            <!-- File contents editor -->
            <div style="margin-bottom: 8px;">
                <label style="font-weight: bold; display: block; margin-bottom: 4px;">
                    File Contents: <code style="font-weight: normal; color: #666;">{source_file}</code>
                </label>
                {"<div style='color: #dc3545; margin-bottom: 8px;'>" + error + "</div>" if error else ""}
                <textarea id="{widget_id}_contents"
                          style="width: 100%; height: {min(400, max(150, line_count * 18))}px; font-family: monospace; font-size: 12px;
                                 padding: 8px; border: 1px solid #ccc; border-radius: 4px; resize: vertical;"
                          placeholder="Enter URLs, one per line...">{escaped_contents}</textarea>
            </div>

            <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                <button type="button" id="{widget_id}_save_btn"
                        onclick="saveSeedUrls_{widget_id}()"
                        style="padding: 8px 20px; background: #417690; color: white; border: none;
                               border-radius: 4px; cursor: pointer; font-weight: bold;">
                    Save URLs
                </button>
                <span id="{widget_id}_line_count" style="color: #666; font-size: 12px;"></span>
                <span id="{widget_id}_status" style="color: #666; font-size: 12px;"></span>
            </div>
            '''}

            {"" if is_file else f'''
            <div style="margin-top: 8px; color: #666;">
                <a href="{seed_uri}" target="_blank">{seed_uri}</a>
            </div>
            '''}

            <script>
                (function() {{
                    var uriInput = document.getElementById('{widget_id}_uri');
                    var contentsInput = document.getElementById('{widget_id}_contents');
                    var status = document.getElementById('{widget_id}_status');
                    var lineCount = document.getElementById('{widget_id}_line_count');
                    var saveBtn = document.getElementById('{widget_id}_save_btn');

                    // Auto-resize URI input
                    function autoResizeUri() {{
                        uriInput.style.height = 'auto';
                        uriInput.style.height = Math.min(100, uriInput.scrollHeight) + 'px';
                    }}
                    uriInput.addEventListener('input', autoResizeUri);
                    autoResizeUri();

                    if (contentsInput) {{
                        function updateLineCount() {{
                            var lines = contentsInput.value.split('\\n').filter(function(l) {{ return l.trim(); }});
                            lineCount.textContent = lines.length + ' URLs';
                        }}

                        contentsInput.addEventListener('input', function() {{
                            updateLineCount();
                            if (status) {{
                                status.textContent = '(unsaved changes)';
                                status.style.color = '#c4820e';
                            }}
                        }});

                        updateLineCount();
                    }}

                    window.saveSeedUrls_{widget_id} = function() {{
                        if (!saveBtn) return;
                        saveBtn.disabled = true;
                        saveBtn.textContent = 'Saving...';
                        if (status) status.textContent = '';

                        fetch(window.location.pathname + 'save_seed_contents/', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                            }},
                            body: JSON.stringify({{ contents: contentsInput ? contentsInput.value : '' }})
                        }})
                        .then(function(response) {{ return response.json(); }})
                        .then(function(data) {{
                            if (data.success) {{
                                if (status) {{
                                    status.textContent = '✓ ' + data.message;
                                    status.style.color = '#28a745';
                                }}
                            }} else {{
                                if (status) {{
                                    status.textContent = '✗ ' + data.error;
                                    status.style.color = '#dc3545';
                                }}
                            }}
                        }})
                        .catch(function(err) {{
                            if (status) {{
                                status.textContent = '✗ Error: ' + err;
                                status.style.color = '#dc3545';
                            }}
                        }})
                        .finally(function() {{
                            saveBtn.disabled = false;
                            saveBtn.textContent = 'Save URLs';
                        }});
                    }};
                }})();
            </script>
        </div>
        '''
        return mark_safe(html)



class CrawlScheduleAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'label', 'notes', 'template_str')
    search_fields = ('id', 'created_by__username', 'label', 'notes', 'schedule_id', 'template_id', 'template__seed__uri')

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
    admin_site.register(Seed, SeedAdmin)
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
