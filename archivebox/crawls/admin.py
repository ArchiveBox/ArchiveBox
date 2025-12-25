__package__ = 'archivebox.crawls'

import json
from pathlib import Path

from django.utils.html import format_html, format_html_join, mark_safe
from django.contrib import admin, messages
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from archivebox import DATA_DIR

from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from core.models import Snapshot
from crawls.models import Seed, Crawl, CrawlSchedule


class SeedAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('id', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str')
    search_fields = ('id', 'created_by__username', 'label', 'notes', 'uri', 'extractor', 'tags_str')

    readonly_fields = ('created_at', 'modified_at', 'scheduled_crawls', 'crawls', 'snapshots', 'contents')
    fields = ('label', 'notes', 'uri', 'extractor', 'tags_str', 'config', 'created_by', *readonly_fields)

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
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in obj.snapshot_set.all().order_by('-created_at')[:20]
        )) or mark_safe('<i>No Snapshots yet...</i>')

    def contents(self, obj):
        if obj.uri.startswith('file:///data/'):
            source_file = DATA_DIR / obj.uri.replace('file:///data/', '', 1)
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
    fields = ('label', 'notes', 'seed_urls_editor', 'config', 'status', 'retry_at', 'max_depth', 'seed', 'schedule', 'created_by', 'created_at', 'modified_at', 'snapshots')

    list_filter = ('max_depth', 'seed', 'schedule', 'created_by', 'status', 'retry_at')
    ordering = ['-created_at', '-retry_at']
    list_per_page = 100
    actions = ["delete_selected"]
    change_actions = ['recrawl']

    @action(label='Recrawl', description='Create a new crawl with the same settings')
    def recrawl(self, request, obj):
        """Duplicate this crawl as a new crawl with the same seed and settings."""
        from django.utils import timezone

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

        # Redirect to the new crawl's change page
        from django.shortcuts import redirect
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

        if not (crawl.seed and crawl.seed.uri and crawl.seed.uri.startswith('file:///data/')):
            return JsonResponse({'success': False, 'error': 'Seed is not a local file'}, status=400)

        try:
            data = json.loads(request.body)
            contents = data.get('contents', '')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

        source_file = DATA_DIR / crawl.seed.uri.replace('file:///data/', '', 1)

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
        return format_html_join('<br/>', '<a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in obj.snapshot_set.all().order_by('-created_at')[:20]
        )) or mark_safe('<i>No Snapshots yet...</i>')

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
        is_file = seed_uri.startswith('file:///data/')
        contents = ""
        error = None
        source_file = None

        if is_file:
            source_file = DATA_DIR / seed_uri.replace('file:///data/', '', 1)
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
    fields = ('label', 'notes', 'schedule', 'template', 'created_by', *readonly_fields)

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
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in Snapshot.objects.filter(crawl_id__in=crawl_ids).order_by('-created_at')[:20]
        )) or mark_safe('<i>No Snapshots yet...</i>')


def register_admin(admin_site):
    admin_site.register(Seed, SeedAdmin)
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
