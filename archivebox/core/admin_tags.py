__package__ = 'archivebox.core'

from django.contrib import admin
from django.utils.html import format_html, mark_safe

import abx

from archivebox.abid_utils.admin import ABIDModelAdmin
from archivebox.misc.paginators import AccelleratedPaginator


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
    

# class AutocompleteTags:
#     model = Tag
#     search_fields = ['name']
#     name = 'name'
#     # source_field = 'name'
#     remote_field = Tag._meta.get_field('name')

# class AutocompleteTagsAdminStub:
#     name = 'admin'
    
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



# @admin.register(SnapshotTag, site=archivebox_admin)
# class SnapshotTagAdmin(ABIDModelAdmin):
#     list_display = ('id', 'snapshot', 'tag')
#     sort_fields = ('id', 'snapshot', 'tag')
#     search_fields = ('id', 'snapshot_id', 'tag_id')
#     fields = ('snapshot', 'id')
#     actions = ['delete_selected']
#     ordering = ['-id']


@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(Tag, TagAdmin)

