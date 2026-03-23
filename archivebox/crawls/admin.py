__package__ = 'archivebox.crawls'

from django import forms
from django.http import JsonResponse, HttpRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import escape, format_html, format_html_join
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.contrib import admin, messages
from django.db.models import Count, Q


from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from archivebox.core.models import Snapshot
from archivebox.core.widgets import TagEditorWidget
from archivebox.crawls.models import Crawl, CrawlSchedule


def render_snapshots_list(snapshots_qs, limit=20, crawl=None):
    """Render a nice inline list view of snapshots with status, title, URL, and progress."""

    snapshots = snapshots_qs.order_by('-created_at')[:limit].annotate(
        total_results=Count('archiveresult'),
        succeeded_results=Count('archiveresult', filter=Q(archiveresult__status='succeeded')),
        failed_results=Count('archiveresult', filter=Q(archiveresult__status='failed')),
        started_results=Count('archiveresult', filter=Q(archiveresult__status='started')),
        skipped_results=Count('archiveresult', filter=Q(archiveresult__status='skipped')),
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
        succeeded = snapshot.succeeded_results
        failed = snapshot.failed_results
        running = snapshot.started_results
        skipped = snapshot.skipped_results
        done = succeeded + failed + skipped
        pending = max(total - done - running, 0)
        progress_pct = int((done / total) * 100) if total > 0 else 0
        progress_text = f'{done}/{total}' if total > 0 else '-'
        progress_title = (
            f'{succeeded} succeeded, {failed} failed, {running} running, '
            f'{pending} pending, {skipped} skipped'
        )
        progress_color = '#28a745'
        if failed:
            progress_color = '#dc3545'
        elif running:
            progress_color = '#17a2b8'
        elif pending:
            progress_color = '#ffc107'

        # Truncate title and URL
        snapshot_title = snapshot.title or 'Untitled'
        title = snapshot_title[:60]
        if len(snapshot_title) > 60:
            title += '...'
        url_display = snapshot.url[:50]
        if len(snapshot.url) > 50:
            url_display += '...'
        delete_button = ''
        exclude_button = ''
        if crawl is not None:
            delete_url = reverse('admin:crawls_crawl_snapshot_delete', args=[crawl.pk, snapshot.pk])
            exclude_url = reverse('admin:crawls_crawl_snapshot_exclude_domain', args=[crawl.pk, snapshot.pk])
            delete_button = f'''
                <button type="button"
                        class="crawl-snapshots-action"
                        data-post-url="{escape(delete_url)}"
                        data-confirm="Delete this snapshot from the crawl?"
                        title="Delete this snapshot from the crawl and remove its URL from the crawl queue."
                        aria-label="Delete snapshot"
                        style="border: 1px solid #ddd; background: #fff; color: #666; border-radius: 4px; width: 28px; height: 28px; cursor: pointer;">🗑</button>
            '''
            exclude_button = f'''
                <button type="button"
                        class="crawl-snapshots-action"
                        data-post-url="{escape(exclude_url)}"
                        data-confirm="Exclude this domain from the crawl? This removes matching queued URLs, deletes pending matching snapshots, and blocks future matches."
                        title="Exclude this domain from this crawl. This removes matching URLs from the crawl queue, deletes pending matching snapshots, and blocks future matches."
                        aria-label="Exclude domain from crawl"
                        style="border: 1px solid #ddd; background: #fff; color: #666; border-radius: 4px; width: 28px; height: 28px; cursor: pointer;">⊘</button>
            '''

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
                       title="{escape(snapshot_title)}">{escape(title)}</a>
                </td>
                <td style="padding: 6px 8px; max-width: 250px;">
                    <a href="{escape(snapshot.url)}" target="_blank"
                       style="color: #666; text-decoration: none; font-family: monospace; font-size: 11px;"
                       title="{escape(snapshot.url)}">{escape(url_display)}</a>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; text-align: center;">
                    <div style="display: inline-flex; align-items: center; gap: 6px;" title="{escape(progress_title)}">
                        <div style="width: 60px; height: 6px; background: #eee; border-radius: 3px; overflow: hidden;">
                            <div style="width: {progress_pct}%; height: 100%;
                                        background: {progress_color};
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
                {"<td style=\"padding: 6px 8px; white-space: nowrap; text-align: right;\"><div style=\"display: inline-flex; gap: 6px;\">%s%s</div></td>" % (exclude_button, delete_button) if crawl is not None else ""}
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
        <div data-crawl-snapshots-list style="border: 1px solid #ddd; border-radius: 6px; overflow: hidden; max-width: 100%;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #f5f5f5; border-bottom: 2px solid #ddd;">
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Status</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333; width: 24px;"></th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Title</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">URL</th>
                        <th style="padding: 8px; text-align: center; font-weight: 600; color: #333;">Progress</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Created</th>
                        {'<th style="padding: 8px; text-align: right; font-weight: 600; color: #333;">Actions</th>' if crawl is not None else ''}
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                    {footer}
                </tbody>
            </table>
        </div>
        {'''
        <script>
        (function() {
            if (window.__archiveboxCrawlSnapshotActionsBound) {
                return;
            }
            window.__archiveboxCrawlSnapshotActionsBound = true;

            function getCookie(name) {
                var cookieValue = null;
                if (!document.cookie) {
                    return cookieValue;
                }
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
                return cookieValue;
            }

            document.addEventListener('click', function(event) {
                var button = event.target.closest('.crawl-snapshots-action');
                if (!button) {
                    return;
                }
                event.preventDefault();

                var confirmMessage = button.getAttribute('data-confirm');
                if (confirmMessage && !window.confirm(confirmMessage)) {
                    return;
                }

                button.disabled = true;

                fetch(button.getAttribute('data-post-url'), {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': getCookie('csrftoken') || '',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }).then(function(response) {
                    return response.json().then(function(data) {
                        if (!response.ok) {
                            throw new Error(data.error || 'Request failed');
                        }
                        return data;
                    });
                }).then(function() {
                    window.location.reload();
                }).catch(function(error) {
                    button.disabled = false;
                    window.alert(error.message || 'Request failed');
                });
            });
        })();
        </script>
        ''' if crawl is not None else ''}
    ''')


class URLFiltersWidget(forms.Widget):
    def render(self, name, value, attrs=None, renderer=None):
        value = value if isinstance(value, dict) else {}
        widget_id = (attrs or {}).get('id', name)
        allowlist = escape(value.get('allowlist', '') or '')
        denylist = escape(value.get('denylist', '') or '')

        return mark_safe(f'''
            <div id="{widget_id}_container" style="min-width: 420px;">
                <input type="hidden" name="{name}" value="">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div>
                        <label for="{widget_id}_allowlist" style="display: block; font-weight: 600; margin-bottom: 4px;">Allowlist</label>
                        <textarea id="{widget_id}_allowlist" name="{name}_allowlist" rows="3"
                                  style="width: 100%; font-family: monospace; font-size: 12px;"
                                  placeholder="example.com&#10;*.example.com">{allowlist}</textarea>
                    </div>
                    <div>
                        <label for="{widget_id}_denylist" style="display: block; font-weight: 600; margin-bottom: 4px;">Denylist</label>
                        <textarea id="{widget_id}_denylist" name="{name}_denylist" rows="3"
                                  style="width: 100%; font-family: monospace; font-size: 12px;"
                                  placeholder="static.example.com">{denylist}</textarea>
                    </div>
                </div>
                <label style="display: inline-flex; align-items: center; gap: 6px; margin-top: 8px; font-weight: 500;">
                    <input type="checkbox" id="{widget_id}_same_domain_only" name="{name}_same_domain_only" value="1">
                    Same domain only
                </label>
                <p style="color: #666; font-size: 11px; margin: 6px 0 0 0;">
                    Enter domains, wildcards, or regex patterns. Denylist takes precedence over allowlist.
                </p>
                <script>
                    (function() {{
                        if (window.__archiveboxUrlFilterEditors && window.__archiveboxUrlFilterEditors['{widget_id}']) {{
                            return;
                        }}
                        window.__archiveboxUrlFilterEditors = window.__archiveboxUrlFilterEditors || {{}};
                        window.__archiveboxUrlFilterEditors['{widget_id}'] = true;

                        var urlsField = document.getElementById('id_urls');
                        var allowlistField = document.getElementById('{widget_id}_allowlist');
                        var sameDomainOnly = document.getElementById('{widget_id}_same_domain_only');

                        function extractUrl(line) {{
                            var trimmed = (line || '').trim();
                            if (!trimmed || trimmed.charAt(0) === '#') {{
                                return '';
                            }}
                            if (trimmed.charAt(0) === '{{') {{
                                try {{
                                    var record = JSON.parse(trimmed);
                                    return String(record.url || '').trim();
                                }} catch (error) {{
                                    return '';
                                }}
                            }}
                            return trimmed;
                        }}

                        function syncAllowlistFromUrls() {{
                            if (!urlsField || !allowlistField || !sameDomainOnly || !sameDomainOnly.checked) {{
                                return;
                            }}
                            var domains = [];
                            var seen = Object.create(null);
                            urlsField.value.split(/\\n+/).forEach(function(line) {{
                                var url = extractUrl(line);
                                if (!url) {{
                                    return;
                                }}
                                try {{
                                    var parsed = new URL(url);
                                    var domain = (parsed.hostname || '').toLowerCase();
                                    if (domain && !seen[domain]) {{
                                        seen[domain] = true;
                                        domains.push(domain);
                                    }}
                                }} catch (error) {{
                                    return;
                                }}
                            }});
                            allowlistField.value = domains.join('\\n');
                        }}

                        if (sameDomainOnly) {{
                            sameDomainOnly.addEventListener('change', syncAllowlistFromUrls);
                        }}
                        if (urlsField) {{
                            urlsField.addEventListener('input', syncAllowlistFromUrls);
                            urlsField.addEventListener('change', syncAllowlistFromUrls);
                        }}
                    }})();
                </script>
            </div>
        ''')

    def value_from_datadict(self, data, files, name):
        return {
            'allowlist': data.get(f'{name}_allowlist', ''),
            'denylist': data.get(f'{name}_denylist', ''),
            'same_domain_only': data.get(f'{name}_same_domain_only') in ('1', 'on', 'true'),
        }


class URLFiltersField(forms.Field):
    widget = URLFiltersWidget

    def to_python(self, value):
        if isinstance(value, dict):
            return value
        return {'allowlist': '', 'denylist': '', 'same_domain_only': False}


class CrawlAdminForm(forms.ModelForm):
    """Custom form for Crawl admin to render urls field as textarea."""
    tags_editor = forms.CharField(
        label='Tags',
        required=False,
        widget=TagEditorWidget(),
        help_text='Type tag names and press Enter or Space to add. Click × to remove.',
    )
    url_filters = URLFiltersField(
        label='URL Filters',
        required=False,
        help_text='Set URL_ALLOWLIST / URL_DENYLIST for this crawl.',
    )

    class Meta:
        model = Crawl
        fields = '__all__'
        widgets = {
            'urls': forms.Textarea(attrs={
                'rows': 8,
                'style': 'width: 100%; font-family: monospace; font-size: 13px;',
                'placeholder': 'https://example.com\nhttps://example2.com\n# Comments start with #',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 1,
                'style': 'width: 100%; min-height: 0; resize: vertical;',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = dict(self.instance.config or {}) if self.instance and self.instance.pk else {}
        if self.instance and self.instance.pk:
            self.initial['tags_editor'] = self.instance.tags_str
        self.initial['url_filters'] = {
            'allowlist': config.get('URL_ALLOWLIST', ''),
            'denylist': config.get('URL_DENYLIST', ''),
            'same_domain_only': False,
        }

    def clean_tags_editor(self):
        tags_str = self.cleaned_data.get('tags_editor', '')
        tag_names = []
        seen = set()
        for raw_name in tags_str.split(','):
            name = raw_name.strip()
            if not name:
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tag_names.append(name)
        return ','.join(tag_names)

    def clean_url_filters(self):
        value = self.cleaned_data.get('url_filters') or {}
        return {
            'allowlist': '\n'.join(Crawl.split_filter_patterns(value.get('allowlist', ''))),
            'denylist': '\n'.join(Crawl.split_filter_patterns(value.get('denylist', ''))),
            'same_domain_only': bool(value.get('same_domain_only')),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.tags_str = self.cleaned_data.get('tags_editor', '')
        url_filters = self.cleaned_data.get('url_filters') or {}
        instance.set_url_filters(
            url_filters.get('allowlist', ''),
            url_filters.get('denylist', ''),
        )
        if commit:
            instance.save()
            instance.apply_crawl_config_filters()
            save_m2m = getattr(self, '_save_m2m', None)
            if callable(save_m2m):
                save_m2m()
        return instance


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
            'fields': ('label', 'notes', 'tags_editor'),
            'classes': ('card',),
        }),
        ('Settings', {
            'fields': (('max_depth', 'url_filters'), 'config'),
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
    add_fieldsets = (
        ('URLs', {
            'fields': ('urls',),
            'classes': ('card', 'wide'),
        }),
        ('Info', {
            'fields': ('label', 'notes', 'tags_editor'),
            'classes': ('card',),
        }),
        ('Settings', {
            'fields': (('max_depth', 'url_filters'), 'config'),
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

    def get_fieldsets(self, request, obj=None):
        return self.fieldsets if obj else self.add_fieldsets

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/snapshot/<path:snapshot_id>/delete/',
                self.admin_site.admin_view(self.delete_snapshot_view),
                name='crawls_crawl_snapshot_delete',
            ),
            path(
                '<path:object_id>/snapshot/<path:snapshot_id>/exclude-domain/',
                self.admin_site.admin_view(self.exclude_domain_view),
                name='crawls_crawl_snapshot_exclude_domain',
            ),
        ]
        return custom_urls + urls

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
        return render_snapshots_list(obj.snapshot_set.all(), crawl=obj)

    def delete_snapshot_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)

        if snapshot.status == Snapshot.StatusChoices.STARTED:
            snapshot.cancel_running_hooks()

        removed_urls = crawl.prune_url(snapshot.url)
        snapshot.delete()
        return JsonResponse({
            'ok': True,
            'snapshot_id': str(snapshot.id),
            'removed_urls': removed_urls,
        })

    def exclude_domain_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)
        result = crawl.exclude_domain(snapshot.url)
        return JsonResponse({
            'ok': True,
            **result,
        })

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
