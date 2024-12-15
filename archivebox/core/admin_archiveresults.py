__package__ = 'archivebox.core'

import os
from pathlib import Path

from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.core.exceptions import ValidationError
from django.urls import reverse, resolve
from django.utils import timezone
from django_jsonform.forms.fields import JSONFormField

from huey_monitor.admin import TaskModel

import abx

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.paginators import AccelleratedPaginator
from archivebox.base_models.admin import ABIDModelAdmin


from core.models import ArchiveResult, Snapshot




def result_url(result: TaskModel) -> str:
    url = reverse("admin:huey_monitor_taskmodel_change", args=[str(result.id)])
    return format_html('<a href="{url}" class="fade-in-progress-url">See progress...</a>'.format(url=url))



class ArchiveResultInline(admin.TabularInline):
    name = 'Archive Results Log'
    model = ArchiveResult
    parent_model = Snapshot
    # fk_name = 'snapshot'
    extra = 0
    sort_fields = ('end_ts', 'extractor', 'output', 'status', 'cmd_version')
    readonly_fields = ('id', 'result_id', 'completed', 'command', 'version')
    fields = ('start_ts', 'end_ts', *readonly_fields, 'extractor', 'cmd', 'cmd_version', 'pwd', 'created_by', 'status', 'retry_at', 'output')
    # exclude = ('id',)
    ordering = ('end_ts',)
    show_change_link = True
    # # classes = ['collapse']
    # # list_display_links = ['abid']

    def get_parent_object_from_request(self, request):
        resolved = resolve(request.path_info)
        try:
            return self.parent_model.objects.get(pk=resolved.kwargs['object_id'])
        except (self.parent_model.DoesNotExist, ValidationError):
            return self.parent_model.objects.get(pk=self.parent_model.id_from_abid(resolved.kwargs['object_id']))

    @admin.display(
        description='Completed',
        ordering='end_ts',
    )
    def completed(self, obj):
        return format_html('<p style="white-space: nowrap">{}</p>', obj.end_ts.strftime('%Y-%m-%d %H:%M:%S'))

    def result_id(self, obj):
        return format_html('<a href="{}"><code style="font-size: 10px">[{}]</code></a>', reverse('admin:core_archiveresult_change', args=(obj.id,)), obj.abid)
    
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
        formset.form.base_fields['pwd'].initial = str(snapshot.link_dir)
        formset.form.base_fields['created_by'].initial = request.user
        formset.form.base_fields['cmd'] = JSONFormField(initial=['-'])
        formset.form.base_fields['output'].initial = 'Manually recorded cmd output...'
        
        if obj is not None:
            # hidden values for existing entries and new entries
            formset.form.base_fields['start_ts'].widget = formset.form.base_fields['start_ts'].hidden_widget()
            formset.form.base_fields['end_ts'].widget = formset.form.base_fields['end_ts'].hidden_widget()
            formset.form.base_fields['cmd'].widget = formset.form.base_fields['cmd'].hidden_widget()
            formset.form.base_fields['pwd'].widget = formset.form.base_fields['pwd'].hidden_widget()
            formset.form.base_fields['created_by'].widget = formset.form.base_fields['created_by'].hidden_widget()
            formset.form.base_fields['cmd_version'].widget = formset.form.base_fields['cmd_version'].hidden_widget()
        return formset
    
    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return self.readonly_fields
        else:
            return []



class ArchiveResultAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_by', 'created_at', 'snapshot_info', 'tags_str', 'status', 'extractor', 'cmd_str', 'output_str')
    sort_fields = ('abid', 'created_by', 'created_at', 'extractor', 'status')
    readonly_fields = ('cmd_str', 'snapshot_info', 'tags_str', 'created_at', 'modified_at', 'abid_info', 'output_summary')
    search_fields = ('id', 'abid', 'snapshot__url', 'extractor', 'output', 'cmd_version', 'cmd', 'snapshot__timestamp')
    fields = ('snapshot', 'extractor', 'status', 'retry_at', 'start_ts', 'end_ts', 'created_by', 'pwd', 'cmd_version', 'cmd', 'output', *readonly_fields)
    autocomplete_fields = ['snapshot']

    list_filter = ('status', 'extractor', 'start_ts', 'cmd_version')
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
            '<a href="/archive/{}/index.html"><b><code>[{}]</code></b> &nbsp; {} &nbsp; {}</a><br/>',
            result.snapshot.timestamp,
            result.snapshot.abid,
            result.snapshot.bookmarked_at.strftime('%Y-%m-%d %H:%M'),
            result.snapshot.url[:128],
        )


    @admin.display(
        description='Snapshot Tags'
    )
    def tags_str(self, result):
        return result.snapshot.tags_str()

    def cmd_str(self, result):
        return format_html(
            '<pre>{}</pre>',
            ' '.join(result.cmd) if isinstance(result.cmd, list) else str(result.cmd),
        )
    
    def output_str(self, result):
        return format_html(
            '<a href="/archive/{}/{}" class="output-link">↗️</a><pre>{}</pre>',
            result.snapshot.timestamp,
            result.output if (result.status == 'succeeded') and result.extractor not in ('title', 'archive_org') else 'index.html',
            result.output,
        )

    def output_summary(self, result):
        snapshot_dir = Path(DATA_DIR) / str(result.pwd).split('data/', 1)[-1]
        output_str = format_html(
            '<pre style="display: inline-block">{}</pre><br/>',
            result.output,
        )
        output_str += format_html('<a href="/archive/{}/index.html#all">See result files ...</a><br/><pre><code>', str(result.snapshot.timestamp))
        path_from_output_str = (snapshot_dir / (result.output or ''))
        output_str += format_html('<i style="padding: 1px">{}</i><b style="padding-right: 20px">/</b><i>{}</i><br/><hr/>', str(snapshot_dir), str(result.output))
        if os.access(path_from_output_str, os.R_OK):
            root_dir = str(path_from_output_str)
        else:
            root_dir = str(snapshot_dir)

        # print(root_dir, str(list(os.walk(root_dir))))

        for root, dirs, files in os.walk(root_dir):
            depth = root.replace(root_dir, '').count(os.sep) + 1
            if depth > 2:
                continue
            indent = ' ' * 4 * (depth)
            output_str += format_html('<b style="padding: 1px">{}{}/</b><br/>', indent, os.path.basename(root))
            indentation_str = ' ' * 4 * (depth + 1)
            for filename in sorted(files):
                is_hidden = filename.startswith('.')
                output_str += format_html('<span style="opacity: {}.2">{}{}</span><br/>', int(not is_hidden), indentation_str, filename.strip())

        return output_str + format_html('</code></pre>')




@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(ArchiveResult, ArchiveResultAdmin)
