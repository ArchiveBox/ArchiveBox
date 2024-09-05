__package__ = 'archivebox.core'

import os
import json

from io import StringIO
from pathlib import Path
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Dict, Any

from django.contrib import admin
from django.db.models import Count, Q, Prefetch
from django.urls import path, reverse, resolve
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.template import Template, RequestContext
from django.conf import settings
from django import forms


from signal_webhooks.admin import WebhookAdmin
from signal_webhooks.utils import get_webhook_model
# from plugantic.admin import CustomPlugin

from ..util import htmldecode, urldecode, ansi_to_html

from core.models import Snapshot, ArchiveResult, Tag, SnapshotTag
from core.forms import AddLinkForm
from core.mixins import SearchResultsAdminMixin
from api.models import APIToken
from api.auth import get_or_create_api_token
from abid_utils.models import get_or_create_system_user_pk
from abid_utils.admin import ABIDModelAdmin

from index.html import snapshot_icons
from logging_util import printable_filesize
from main import add, remove
from extractors import archive_links


CONFIG = settings.CONFIG

GLOBAL_CONTEXT = {'VERSION': CONFIG.VERSION, 'VERSIONS_AVAILABLE': CONFIG.VERSIONS_AVAILABLE, 'CAN_UPGRADE': CONFIG.CAN_UPGRADE}

# Admin URLs
# /admin/
# /admin/login/
# /admin/core/
# /admin/core/snapshot/
# /admin/core/snapshot/:uuid/
# /admin/core/tag/
# /admin/core/tag/:uuid/


# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel


class ArchiveBoxAdmin(admin.AdminSite):
    site_header = 'ArchiveBox'
    index_title = 'Links'
    site_title = 'Index'
    namespace = 'admin'

    def get_urls(self):
        return [
            path('core/snapshot/add/', self.add_view, name='Add'),
        ] + super().get_urls()

    def add_view(self, request):
        if not request.user.is_authenticated:
            return redirect(f'/admin/login/?next={request.path}')

        request.current_app = self.name
        context: Dict[str, Any] = {
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
                    "out_dir": CONFIG.OUTPUT_DIR,
                }
                add_stdout = StringIO()
                with redirect_stdout(add_stdout):
                   add(**input_kwargs)
                print(add_stdout.getvalue())

                context.update({
                    "stdout": ansi_to_html(add_stdout.getvalue().strip()),
                    "form": AddLinkForm(),
                })
            else:
                context["form"] = form

        return render(template_name='add.html', request=request, context=context)


class CustomUserAdmin(UserAdmin):
    sort_fields = ['id', 'email', 'username', 'is_superuser', 'last_login', 'date_joined']
    list_display = ['username', 'id', 'email', 'is_superuser', 'last_login', 'date_joined']
    readonly_fields = ('snapshot_set', 'archiveresult_set', 'tag_set', 'apitoken_set', 'outboundwebhook_set')
    fieldsets = [*UserAdmin.fieldsets, ('Data', {'fields': readonly_fields})]

    @admin.display(description='Snapshots')
    def snapshot_set(self, obj):
        total_count = obj.snapshot_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/core/snapshot/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> {}',
                snap.pk,
                snap.abid,
                snap.downloaded_at.strftime('%Y-%m-%d %H:%M') if snap.downloaded_at else 'pending...',
                snap.url[:64],
            )
            for snap in obj.snapshot_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/snapshot/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='Archive Result Logs')
    def archiveresult_set(self, obj):
        total_count = obj.archiveresult_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/core/archiveresult/{}/change"><b>[{}]</b></a></code> <b>📅 {}</b> <b>📄 {}</b> {}',
                result.pk,
                result.abid,
                result.snapshot.downloaded_at.strftime('%Y-%m-%d %H:%M') if result.snapshot.downloaded_at else 'pending...',
                result.extractor,
                result.snapshot.url[:64],
            )
            for result in obj.archiveresult_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/archiveresult/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='Tags')
    def tag_set(self, obj):
        total_count = obj.tag_set.count()
        return mark_safe(', '.join(
            format_html(
                '<code><a href="/admin/core/tag/{}/change"><b>{}</b></a></code>',
                tag.pk,
                tag.name,
            )
            for tag in obj.tag_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/core/tag/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='API Tokens')
    def apitoken_set(self, obj):
        total_count = obj.apitoken_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/api/apitoken/{}/change"><b>[{}]</b></a></code> {} (expires {})',
                apitoken.pk,
                apitoken.abid,
                apitoken.token_redacted[:64],
                apitoken.expires,
            )
            for apitoken in obj.apitoken_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/api/apitoken/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')

    @admin.display(description='API Outbound Webhooks')
    def outboundwebhook_set(self, obj):
        total_count = obj.outboundwebhook_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/api/outboundwebhook/{}/change"><b>[{}]</b></a></code> {} -> {}',
                outboundwebhook.pk,
                outboundwebhook.abid,
                outboundwebhook.referenced_model,
                outboundwebhook.endpoint,
            )
            for outboundwebhook in obj.outboundwebhook_set.order_by('-modified_at')[:10]
        ) + f'<br/><a href="/admin/api/outboundwebhook/?created_by__id__exact={obj.pk}">{total_count} total records...<a>')


archivebox_admin = ArchiveBoxAdmin()
archivebox_admin.register(get_user_model(), CustomUserAdmin)
archivebox_admin.disable_action('delete_selected')

# archivebox_admin.register(CustomPlugin)

# patch admin with methods to add data views (implemented by admin_data_views package)
# https://github.com/MrThearMan/django-admin-data-views
# https://mrthearman.github.io/django-admin-data-views/setup/
############### Additional sections are defined in settings.ADMIN_DATA_VIEWS #########
from admin_data_views.admin import get_app_list, admin_data_index_view, get_admin_data_urls, get_urls

archivebox_admin.get_app_list = get_app_list.__get__(archivebox_admin, ArchiveBoxAdmin)
archivebox_admin.admin_data_index_view = admin_data_index_view.__get__(archivebox_admin, ArchiveBoxAdmin)       # type: ignore
archivebox_admin.get_admin_data_urls = get_admin_data_urls.__get__(archivebox_admin, ArchiveBoxAdmin)           # type: ignore
archivebox_admin.get_urls = get_urls(archivebox_admin.get_urls).__get__(archivebox_admin, ArchiveBoxAdmin)


class AccelleratedPaginator(Paginator):
    """
    Accellerated Pagniator ignores DISTINCT when counting total number of rows.
    Speeds up SELECT Count(*) on Admin views by >20x.
    https://hakibenita.com/optimizing-the-django-admin-paginator
    """

    @cached_property
    def count(self):
        if self.object_list._has_filters():                             # type: ignore
            # fallback to normal count method on filtered queryset
            return super().count
        else:
            # otherwise count total rows in a separate fast query
            return self.object_list.model.objects.count()
    
        # Alternative approach for PostgreSQL: fallback count takes > 200ms
        # from django.db import connection, transaction, OperationalError
        # with transaction.atomic(), connection.cursor() as cursor:
        #     cursor.execute('SET LOCAL statement_timeout TO 200;')
        #     try:
        #         return super().count
        #     except OperationalError:
        #         return 9999999999999


class ArchiveResultInline(admin.TabularInline):
    name = 'Archive Results Log'
    model = ArchiveResult
    parent_model = Snapshot
    # fk_name = 'snapshot'
    extra = 0
    sort_fields = ('end_ts', 'extractor', 'output', 'status', 'cmd_version')
    readonly_fields = ('id', 'result_id', 'completed', 'command', 'version')
    fields = ('start_ts', 'end_ts', *readonly_fields, 'extractor', 'cmd', 'cmd_version', 'pwd', 'created_by', 'status', 'output')
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
        formset.form.base_fields['cmd'] = forms.JSONField(initial=['-'])
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


class TagInline(admin.TabularInline):
    model = Tag.snapshot_set.through       # type: ignore
    # fk_name = 'snapshot'
    fields = ('id', 'tag')
    extra = 1
    # min_num = 1
    max_num = 1000
    autocomplete_fields = (
        'tag',
    )

from django.contrib.admin.helpers import ActionForm
from django.contrib.admin.widgets import FilteredSelectMultiple

# class AutocompleteTags:
#     model = Tag
#     search_fields = ['name']
#     name = 'name'
#     # source_field = 'name'
#     remote_field = Tag._meta.get_field('name')

# class AutocompleteTagsAdminStub:
#     name = 'admin'


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





@admin.register(Snapshot, site=archivebox_admin)
class SnapshotAdmin(SearchResultsAdminMixin, ABIDModelAdmin):
    list_display = ('created_at', 'title_str', 'files', 'size', 'url_str')
    sort_fields = ('title_str', 'url_str', 'created_at')
    readonly_fields = ('admin_actions', 'status_info', 'tags_str', 'imported_timestamp', 'created_at', 'modified_at', 'downloaded_at', 'abid_info', 'link_dir')
    search_fields = ('id', 'url', 'abid', 'timestamp', 'title', 'tags__name')
    list_filter = ('created_at', 'downloaded_at', 'archiveresult__status', 'created_by', 'tags__name')
    fields = ('url', 'title', 'created_by', 'bookmarked_at', *readonly_fields)
    ordering = ['-created_at']
    actions = ['add_tags', 'remove_tags', 'update_titles', 'update_snapshots', 'resnapshot_snapshot', 'overwrite_snapshots', 'delete_snapshots']
    inlines = [TagInline, ArchiveResultInline]
    list_per_page = min(max(5, CONFIG.SNAPSHOTS_PER_PAGE), 5000)

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
        archive_size = (Path(obj.link_dir) / 'index.html').exists() and obj.archive_size
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
        self.list_per_page = CONFIG.SNAPSHOTS_PER_PAGE
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
        archive_links([
            snapshot.as_link()
            for snapshot in queryset
        ], overwrite=True, methods=('title','favicon'), out_dir=CONFIG.OUTPUT_DIR)

    @admin.action(
        description="⬇️ Get Missing"
    )
    def update_snapshots(self, request, queryset):
        archive_links([
            snapshot.as_link()
            for snapshot in queryset
        ], out_dir=CONFIG.OUTPUT_DIR)


    @admin.action(
        description="📑 Archive again"
    )
    def resnapshot_snapshot(self, request, queryset):
        for snapshot in queryset:
            timestamp = datetime.now(timezone.utc).isoformat('T', 'seconds')
            new_url = snapshot.url.split('#')[0] + f'#{timestamp}'
            add(new_url, tag=snapshot.tags_str())

    @admin.action(
        description="♲ Redo"
    )
    def overwrite_snapshots(self, request, queryset):
        archive_links([
            snapshot.as_link()
            for snapshot in queryset
        ], overwrite=True, out_dir=CONFIG.OUTPUT_DIR)

    @admin.action(
        description="☠️ Delete"
    )
    def delete_snapshots(self, request, queryset):
        remove(snapshots=queryset, yes=True, delete=True, out_dir=CONFIG.OUTPUT_DIR)


    @admin.action(
        description="+"
    )
    def add_tags(self, request, queryset):
        tags = request.POST.getlist('tags')
        print('[+] Adding tags', tags, 'to Snapshots', queryset)
        for obj in queryset:
            obj.tags.add(*tags)


    @admin.action(
        description="–"
    )
    def remove_tags(self, request, queryset):
        tags = request.POST.getlist('tags')
        print('[-] Removing tags', tags, 'to Snapshots', queryset)
        for obj in queryset:
            obj.tags.remove(*tags)


        



# @admin.register(SnapshotTag, site=archivebox_admin)
# class SnapshotTagAdmin(ABIDModelAdmin):
#     list_display = ('id', 'snapshot', 'tag')
#     sort_fields = ('id', 'snapshot', 'tag')
#     search_fields = ('id', 'snapshot_id', 'tag_id')
#     fields = ('snapshot', 'id')
#     actions = ['delete_selected']
#     ordering = ['-id']



@admin.register(Tag, site=archivebox_admin)
class TagAdmin(ABIDModelAdmin):
    list_display = ('created_at', 'created_by', 'abid', 'name', 'num_snapshots', 'snapshots')
    list_filter = ('created_at', 'created_by')
    sort_fields = ('name', 'slug', 'abid', 'created_by', 'created_at')
    readonly_fields = ('slug', 'abid', 'created_at', 'modified_at', 'abid_info', 'snapshots')
    search_fields = ('abid', 'name', 'slug')
    fields = ('name', 'created_by', *readonly_fields)
    actions = ['delete_selected']
    ordering = ['-created_at']

    paginator = AccelleratedPaginator


    def num_snapshots(self, tag):
        return format_html(
            '<a href="/admin/core/snapshot/?tags__id__exact={}">{} total</a>',
            tag.id,
            tag.snapshot_set.count(),
        )

    def snapshots(self, tag):
        total_count = tag.snapshot_set.count()
        return mark_safe('<br/>'.join(
            format_html(
                '<code><a href="/admin/core/snapshot/{}/change"><b>[{}]</b></a></code> {}',
                snap.pk,
                snap.downloaded_at.strftime('%Y-%m-%d %H:%M') if snap.downloaded_at else 'pending...',
                snap.url[:64],
            )
            for snap in tag.snapshot_set.order_by('-downloaded_at')[:10]
        ) + (f'<br/><a href="/admin/core/snapshot/?tags__id__exact={tag.id}">{total_count} total snapshots...<a>'))


@admin.register(ArchiveResult, site=archivebox_admin)
class ArchiveResultAdmin(ABIDModelAdmin):
    list_display = ('start_ts', 'snapshot_info', 'tags_str', 'extractor', 'cmd_str', 'status', 'output_str')
    sort_fields = ('start_ts', 'extractor', 'status')
    readonly_fields = ('cmd_str', 'snapshot_info', 'tags_str', 'created_at', 'modified_at', 'abid_info', 'output_summary')
    search_fields = ('id', 'abid', 'snapshot__url', 'extractor', 'output', 'cmd_version', 'cmd', 'snapshot__timestamp')
    fields = ('snapshot', 'extractor', 'status', 'output', 'pwd', 'start_ts', 'end_ts', 'created_by', 'cmd_version', 'cmd', *readonly_fields)
    autocomplete_fields = ['snapshot']

    list_filter = ('status', 'extractor', 'start_ts', 'cmd_version')
    ordering = ['-start_ts']
    list_per_page = CONFIG.SNAPSHOTS_PER_PAGE
    
    paginator = AccelleratedPaginator
    save_on_top = True

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
        snapshot_dir = Path(CONFIG.OUTPUT_DIR) / str(result.pwd).split('data/', 1)[-1]
        output_str = format_html(
            '<pre style="display: inline-block">{}</pre><br/>',
            result.output,
        )
        output_str += format_html('<a href="/archive/{}/index.html#all">See result files ...</a><br/><pre><code>', str(result.snapshot.timestamp))
        path_from_output_str = (snapshot_dir / result.output)
        output_str += format_html('<i style="padding: 1px">{}</i><b style="padding-right: 20px">/</b><i>{}</i><br/><hr/>', str(snapshot_dir), str(result.output))
        if path_from_output_str.exists():
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



@admin.register(APIToken, site=archivebox_admin)
class APITokenAdmin(ABIDModelAdmin):
    list_display = ('created_at', 'abid', 'created_by', 'token_redacted', 'expires')
    sort_fields = ('abid', 'created_at', 'created_by', 'expires')
    readonly_fields = ('created_at', 'modified_at', 'abid_info')
    search_fields = ('id', 'abid', 'created_by__username', 'token')
    fields = ('created_by', 'token', 'expires', *readonly_fields)

    list_filter = ('created_by',)
    ordering = ['-created_at']
    list_per_page = 100

@admin.register(get_webhook_model(), site=archivebox_admin)
class CustomWebhookAdmin(WebhookAdmin, ABIDModelAdmin):
    list_display = ('created_at', 'created_by', 'abid', *WebhookAdmin.list_display)
    sort_fields = ('created_at', 'created_by', 'abid', 'referenced_model', 'endpoint', 'last_success', 'last_error')
    readonly_fields = ('created_at', 'modified_at', 'abid_info', *WebhookAdmin.readonly_fields)
