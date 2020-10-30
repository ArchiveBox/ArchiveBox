__package__ = 'archivebox.core'

from io import StringIO
from contextlib import redirect_stdout

from django.contrib import admin
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django import forms

from core.models import Snapshot
from core.forms import AddLinkForm, TagField
from core.utils import get_icons

from util import htmldecode, urldecode, ansi_to_html
from logging_util import printable_filesize
from main import add, remove
from config import OUTPUT_DIR
from extractors import archive_links

# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel

def update_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], out_dir=OUTPUT_DIR)
update_snapshots.short_description = "Archive"

def update_titles(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, methods=('title','favicon'), out_dir=OUTPUT_DIR)
update_titles.short_description = "Pull title"

def overwrite_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, out_dir=OUTPUT_DIR)
overwrite_snapshots.short_description = "Re-archive (overwrite)"

def verify_snapshots(modeladmin, request, queryset):
    for snapshot in queryset:
        print(snapshot.timestamp, snapshot.url, snapshot.is_archived, snapshot.archive_size, len(snapshot.history))

verify_snapshots.short_description = "Check"

def delete_snapshots(modeladmin, request, queryset):
    remove(snapshots=queryset, yes=True, delete=True, out_dir=OUTPUT_DIR)

delete_snapshots.short_description = "Delete"


class SnapshotAdminForm(forms.ModelForm):
    tags = TagField(required=False)

    class Meta:
        model = Snapshot
        fields = "__all__"

    def save(self, commit=True):
        # Based on: https://stackoverflow.com/a/49933068/3509554

        # Get the unsave instance
        instance = forms.ModelForm.save(self, False)
        tags = self.cleaned_data.pop("tags")

        #update save_m2m
        def new_save_m2m():
            instance.save_tags(tags)

        # Do we need to save all changes now?
        self.save_m2m = new_save_m2m
        if commit:
            instance.save()

        return instance


class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('added', 'title_str', 'url_str', 'files', 'size')
    sort_fields = ('title_str', 'url_str', 'added')
    readonly_fields = ('id', 'timestamp', 'num_outputs', 'is_archived', 'url_hash', 'added')
    search_fields = ('url', 'timestamp', 'title', 'tags')
    fields = (*readonly_fields, 'title', 'tags')
    list_filter = ('added',)
    ordering = ['-added']
    actions = [delete_snapshots, overwrite_snapshots, update_snapshots, update_titles, verify_snapshots]
    actions_template = 'admin/actions_as_select.html'
    form = SnapshotAdminForm

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('tags')

    def tag_list(self, obj):
        return ', '.join(obj.tags.values_list('name', flat=True))

    def id_str(self, obj):
        return format_html(
            '<code style="font-size: 10px">{}</code>',
            obj.url_hash[:8],
        )

    def title_str(self, obj):
        canon = obj.as_link().canonical_outputs()
        tags = ''.join(
            format_html(' <a href="/admin/core/snapshot/?tags__id__exact={}"><span class="tag">{}</span></a> ', tag.id, tag)
            for tag in obj.tags.all()
        )
        return format_html(
            '<a href="/{}">'
                '<img src="/{}/{}" class="favicon" onerror="this.remove()">'
            '</a>'
            '<a href="/{}/index.html">'
                '<b class="status-{}">{}</b>'
            '</a>',
            obj.archive_path,
            obj.archive_path, canon['favicon_path'],
            obj.archive_path,
            'fetched' if obj.latest_title or obj.title else 'pending',
            urldecode(htmldecode(obj.latest_title or obj.title or ''))[:128] or 'Pending...'
        ) + mark_safe(f'<span class="tags">{tags}</span>')

    def files(self, obj):
        return get_icons(obj)

    def size(self, obj):
        return format_html(
            '<a href="/{}" title="View all files">{}</a>',
            obj.archive_path,
            printable_filesize(obj.archive_size) if obj.archive_size else 'pending',
        )

    def url_str(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            obj.url,
            obj.url.split('://www.', 1)[-1].split('://', 1)[-1][:64],
        )

    id_str.short_description = 'ID'
    title_str.short_description = 'Title'
    url_str.short_description = 'Original URL'

    id_str.admin_order_field = 'id'
    title_str.admin_order_field = 'title'
    url_str.admin_order_field = 'url'



class ArchiveBoxAdmin(admin.AdminSite):
    site_header = 'ArchiveBox'
    index_title = 'Links'
    site_title = 'Index'

    def get_urls(self):
        return [
            path('core/snapshot/add/', self.add_view, name='Add'),
        ] + super().get_urls()

    def add_view(self, request):
        if not request.user.is_authenticated:
            return redirect(f'/admin/login/?next={request.path}')

        request.current_app = self.name
        context = {
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
                    "out_dir": OUTPUT_DIR,
                }
                add_stdout = StringIO()
                with redirect_stdout(add_stdout):
                   add(**input_kwargs)
                print(add_stdout.getvalue())

                context.update({
                    "stdout": ansi_to_html(add_stdout.getvalue().strip()),
                    "form": AddLinkForm()
                })
            else:
                context["form"] = form

        return render(template_name='add_links.html', request=request, context=context)


admin.site = ArchiveBoxAdmin()
admin.site.register(get_user_model())
admin.site.register(Snapshot, SnapshotAdmin)
admin.site.disable_action('delete_selected')
