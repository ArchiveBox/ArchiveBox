__package__ = 'archivebox.core'

import os
from pathlib import Path

from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.core.exceptions import ValidationError
from django.urls import reverse, resolve
from django.utils import timezone

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.paginators import AccelleratedPaginator
from archivebox.base_models.admin import BaseModelAdmin
from archivebox.hooks import get_plugin_icon


from archivebox.core.models import ArchiveResult, Snapshot


def render_archiveresults_list(archiveresults_qs, limit=50):
    """Render a nice inline list view of archive results with status, plugin, output, and actions."""

    results = list(archiveresults_qs.order_by('plugin').select_related('snapshot')[:limit])

    if not results:
        return mark_safe('<div style="color: #64748b; font-style: italic; padding: 16px 0;">No Archive Results yet...</div>')

    # Status colors
    status_colors = {
        'succeeded': ('#166534', '#dcfce7'),   # green
        'failed': ('#991b1b', '#fee2e2'),       # red
        'queued': ('#6b7280', '#f3f4f6'),       # gray
        'started': ('#92400e', '#fef3c7'),      # amber
    }

    rows = []
    for idx, result in enumerate(results):
        status = result.status or 'queued'
        color, bg = status_colors.get(status, ('#6b7280', '#f3f4f6'))

        # Get plugin icon
        icon = get_plugin_icon(result.plugin)

        # Format timestamp
        end_time = result.end_ts.strftime('%Y-%m-%d %H:%M:%S') if result.end_ts else '-'

        # Truncate output for display
        full_output = result.output_str or '-'
        output_display = full_output[:60]
        if len(full_output) > 60:
            output_display += '...'

        # Get full command as tooltip
        cmd_str = ' '.join(result.cmd) if isinstance(result.cmd, list) else str(result.cmd or '-')

        # Build output link - use embed_path() which checks output_files first
        embed_path = result.embed_path() if hasattr(result, 'embed_path') else None
        output_link = f'/{result.snapshot.archive_path}/{embed_path}' if embed_path and result.status == 'succeeded' else f'/{result.snapshot.archive_path}/'

        # Get version - try cmd_version field
        version = result.cmd_version if result.cmd_version else '-'

        # Unique ID for this row's expandable output
        row_id = f'output_{idx}_{str(result.id)[:8]}'

        rows.append(f'''
            <tr style="border-bottom: 1px solid #f1f5f9; transition: background 0.15s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
                <td style="padding: 10px 12px; white-space: nowrap;">
                    <a href="{reverse('admin:core_archiveresult_change', args=[result.id])}"
                       style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 11px;"
                       title="View/edit archive result">
                        <code>{str(result.id)[:8]}</code>
                    </a>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap;">
                    <span style="display: inline-block; padding: 3px 10px; border-radius: 12px;
                                 font-size: 11px; font-weight: 600; text-transform: uppercase;
                                 color: {color}; background: {bg};">{status}</span>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; font-size: 20px;" title="{result.plugin}">
                    {icon}
                </td>
                <td style="padding: 10px 12px; font-weight: 500; color: #334155;">
                        <a href="{output_link}" target="_blank"
                           style="color: #334155; text-decoration: none;"
                       title="View output fullscreen"
                       onmouseover="this.style.color='#2563eb'; this.style.textDecoration='underline';"
                       onmouseout="this.style.color='#334155'; this.style.textDecoration='none';">
                        {result.plugin}
                    </a>
                </td>
                <td style="padding: 10px 12px; max-width: 280px;">
                    <span onclick="document.getElementById('{row_id}').open = !document.getElementById('{row_id}').open"
                          style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px; cursor: pointer;"
                          title="Click to expand full output">
                        {output_display}
                    </span>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; color: #64748b; font-size: 12px;">
                    {end_time}
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; font-family: ui-monospace, monospace; font-size: 11px; color: #64748b;">
                    {version}
                </td>
                <td style="padding: 10px 8px; white-space: nowrap;">
                    <div style="display: flex; gap: 4px;">
                        <a href="{output_link}" target="_blank"
                           style="padding: 4px 8px; background: #f1f5f9; border-radius: 4px; color: #475569; text-decoration: none; font-size: 11px;"
                           title="View output">📄</a>
                        <a href="{reverse('admin:core_archiveresult_change', args=[result.id])}"
                           style="padding: 4px 8px; background: #f1f5f9; border-radius: 4px; color: #475569; text-decoration: none; font-size: 11px;"
                           title="Edit">✏️</a>
                    </div>
                </td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td colspan="8" style="padding: 0 12px 10px 12px;">
                    <details id="{row_id}" style="margin: 0;">
                        <summary style="cursor: pointer; font-size: 11px; color: #94a3b8; user-select: none;">
                            Details &amp; Output
                        </summary>
                        <div style="margin-top: 8px; padding: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; max-height: 200px; overflow: auto;">
                            <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                                <span style="margin-right: 16px;"><b>ID:</b> <code>{str(result.id)}</code></span>
                                <span style="margin-right: 16px;"><b>Version:</b> <code>{version}</code></span>
                                <span style="margin-right: 16px;"><b>PWD:</b> <code>{result.pwd or '-'}</code></span>
                            </div>
                            <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                                <b>Output:</b>
                            </div>
                            <pre style="margin: 0; padding: 8px; background: #1e293b; border-radius: 4px; color: #e2e8f0; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow: auto;">{full_output}</pre>
                            <div style="font-size: 11px; color: #64748b; margin-top: 8px;">
                                <b>Command:</b>
                            </div>
                            <pre style="margin: 0; padding: 8px; background: #1e293b; border-radius: 4px; color: #e2e8f0; font-size: 11px; white-space: pre-wrap; word-break: break-all;">{cmd_str}</pre>
                        </div>
                    </details>
                </td>
            </tr>
        ''')

    total_count = archiveresults_qs.count()
    footer = ''
    if total_count > limit:
        footer = f'''
            <tr>
                <td colspan="8" style="padding: 12px; text-align: center; color: #64748b; font-size: 13px; background: #f8fafc;">
                    Showing {limit} of {total_count} results &nbsp;
                    <a href="/admin/core/archiveresult/?snapshot__id__exact={results[0].snapshot_id if results else ''}"
                       style="color: #2563eb;">View all →</a>
                </td>
            </tr>
        '''

    return mark_safe(f'''
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff; width: 100%;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">ID</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Status</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; width: 32px;"></th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Plugin</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Output</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Completed</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Version</th>
                        <th style="padding: 10px 8px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                    {footer}
                </tbody>
            </table>
        </div>
    ''')



class ArchiveResultInline(admin.TabularInline):
    name = 'Archive Results Log'
    model = ArchiveResult
    parent_model = Snapshot
    # fk_name = 'snapshot'
    extra = 0
    sort_fields = ('end_ts', 'plugin', 'output_str', 'status', 'cmd_version')
    readonly_fields = ('id', 'result_id', 'completed', 'command', 'version')
    fields = ('start_ts', 'end_ts', *readonly_fields, 'plugin', 'cmd', 'cmd_version', 'pwd', 'status', 'retry_at', 'output_str')
    # exclude = ('id',)
    ordering = ('end_ts',)
    show_change_link = True
    # # classes = ['collapse']

    def get_parent_object_from_request(self, request):
        resolved = resolve(request.path_info)
        try:
            return self.parent_model.objects.get(pk=resolved.kwargs['object_id'])
        except (self.parent_model.DoesNotExist, ValidationError):
            return None

    @admin.display(
        description='Completed',
        ordering='end_ts',
    )
    def completed(self, obj):
        return format_html('<p style="white-space: nowrap">{}</p>', obj.end_ts.strftime('%Y-%m-%d %H:%M:%S'))

    def result_id(self, obj):
        return format_html('<a href="{}"><code style="font-size: 10px">[{}]</code></a>', reverse('admin:core_archiveresult_change', args=(obj.id,)), str(obj.id)[:8])
    
    def command(self, obj):
        return format_html('<small><code>{}</code></small>', " ".join(obj.cmd or []))
    
    def version(self, obj):
        return format_html('<small><code>{}</code></small>', obj.cmd_version or '-')
    
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        snapshot = self.get_parent_object_from_request(request)

        # import ipdb; ipdb.set_trace()
        # formset.form.base_fields['id'].widget = formset.form.base_fields['id'].hidden_widget()
        
        # default values for new entries
        formset.form.base_fields['status'].initial = 'succeeded'
        formset.form.base_fields['start_ts'].initial = timezone.now()
        formset.form.base_fields['end_ts'].initial = timezone.now()
        formset.form.base_fields['cmd_version'].initial = '-'
        formset.form.base_fields['pwd'].initial = str(snapshot.output_dir)
        formset.form.base_fields['cmd'].initial = '["-"]'
        formset.form.base_fields['output_str'].initial = 'Manually recorded cmd output...'

        if obj is not None:
            # hidden values for existing entries and new entries
            formset.form.base_fields['start_ts'].widget = formset.form.base_fields['start_ts'].hidden_widget()
            formset.form.base_fields['end_ts'].widget = formset.form.base_fields['end_ts'].hidden_widget()
            formset.form.base_fields['cmd'].widget = formset.form.base_fields['cmd'].hidden_widget()
            formset.form.base_fields['pwd'].widget = formset.form.base_fields['pwd'].hidden_widget()
            formset.form.base_fields['cmd_version'].widget = formset.form.base_fields['cmd_version'].hidden_widget()
        return formset
    
    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return self.readonly_fields
        else:
            return []



class ArchiveResultAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'snapshot_info', 'tags_str', 'status', 'plugin_with_icon', 'cmd_str', 'output_str')
    sort_fields = ('id', 'created_at', 'plugin', 'status')
    readonly_fields = ('cmd_str', 'snapshot_info', 'tags_str', 'created_at', 'modified_at', 'output_summary', 'plugin_with_icon')
    search_fields = ('id', 'snapshot__url', 'plugin', 'output_str', 'cmd_version', 'cmd', 'snapshot__timestamp')
    autocomplete_fields = ['snapshot']

    fieldsets = (
        ('Snapshot', {
            'fields': ('snapshot', 'snapshot_info', 'tags_str'),
            'classes': ('card', 'wide'),
        }),
        ('Plugin', {
            'fields': ('plugin', 'plugin_with_icon', 'status', 'retry_at'),
            'classes': ('card',),
        }),
        ('Timing', {
            'fields': ('start_ts', 'end_ts', 'created_at', 'modified_at'),
            'classes': ('card',),
        }),
        ('Command', {
            'fields': ('cmd', 'cmd_str', 'cmd_version', 'pwd'),
            'classes': ('card',),
        }),
        ('Output', {
            'fields': ('output_str', 'output_json', 'output_files', 'output_size', 'output_mimetypes', 'output_summary'),
            'classes': ('card', 'wide'),
        }),
    )

    list_filter = ('status', 'plugin', 'start_ts')
    ordering = ['-start_ts']
    list_per_page = SERVER_CONFIG.SNAPSHOTS_PER_PAGE

    paginator = AccelleratedPaginator
    save_on_top = True

    actions = ['delete_selected']

    class Meta:
        verbose_name = 'Archive Result'
        verbose_name_plural = 'Archive Results'

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.display(
        description='Snapshot Info'
    )
    def snapshot_info(self, result):
        return format_html(
            '<a href="/{}/index.html"><b><code>[{}]</code></b> &nbsp; {} &nbsp; {}</a><br/>',
            result.snapshot.archive_path,
            str(result.snapshot.id)[:8],
            result.snapshot.bookmarked_at.strftime('%Y-%m-%d %H:%M'),
            result.snapshot.url[:128],
        )


    @admin.display(
        description='Snapshot Tags'
    )
    def tags_str(self, result):
        return result.snapshot.tags_str()

    @admin.display(description='Plugin', ordering='plugin')
    def plugin_with_icon(self, result):
        icon = get_plugin_icon(result.plugin)
        return format_html(
            '<span title="{}">{}</span> {}',
            result.plugin,
            icon,
            result.plugin,
        )

    def cmd_str(self, result):
        return format_html(
            '<pre>{}</pre>',
            ' '.join(result.cmd) if isinstance(result.cmd, list) else str(result.cmd),
        )

    def output_display(self, result):
        # Determine output link path - use embed_path() which checks output_files
        embed_path = result.embed_path() if hasattr(result, 'embed_path') else None
        output_path = embed_path if (result.status == 'succeeded' and embed_path) else 'index.html'
        return format_html(
            '<a href="/{}/{}" class="output-link">↗️</a><pre>{}</pre>',
            result.snapshot.archive_path,
            output_path,
            result.output_str,
        )

    def output_summary(self, result):
        snapshot_dir = Path(DATA_DIR) / str(result.pwd).split('data/', 1)[-1]
        output_html = format_html(
            '<pre style="display: inline-block">{}</pre><br/>',
            result.output_str,
        )
        output_html += format_html('<a href="/{}/index.html#all">See result files ...</a><br/><pre><code>', str(result.snapshot.archive_path))
        embed_path = result.embed_path() if hasattr(result, 'embed_path') else ''
        path_from_embed = (snapshot_dir / (embed_path or ''))
        output_html += format_html('<i style="padding: 1px">{}</i><b style="padding-right: 20px">/</b><i>{}</i><br/><hr/>', str(snapshot_dir), str(embed_path))
        if os.access(path_from_embed, os.R_OK):
            root_dir = str(path_from_embed)
        else:
            root_dir = str(snapshot_dir)

        # print(root_dir, str(list(os.walk(root_dir))))

        for root, dirs, files in os.walk(root_dir):
            depth = root.replace(root_dir, '').count(os.sep) + 1
            if depth > 2:
                continue
            indent = ' ' * 4 * (depth)
            output_html += format_html('<b style="padding: 1px">{}{}/</b><br/>', indent, os.path.basename(root))
            indentation_str = ' ' * 4 * (depth + 1)
            for filename in sorted(files):
                is_hidden = filename.startswith('.')
                output_html += format_html('<span style="opacity: {}.2">{}{}</span><br/>', int(not is_hidden), indentation_str, filename.strip())

        return output_html + mark_safe('</code></pre>')




def register_admin(admin_site):
    admin_site.register(ArchiveResult, ArchiveResultAdmin)
