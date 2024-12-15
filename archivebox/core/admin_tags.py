__package__ = 'archivebox.core'

from django.contrib import admin
from django.utils.html import format_html, mark_safe

import abx

from archivebox.misc.paginators import AccelleratedPaginator
from archivebox.base_models.admin import ABIDModelAdmin

from core.models import Tag


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
    
    
# class TaggedItemInline(admin.TabularInline):
#     readonly_fields = ('object_link',)
#     fields = ('id', 'tag', 'content_type', 'object_id', *readonly_fields)
#     model = TaggedItem
#     extra = 1
#     show_change_link = True
    
#     @admin.display(description='object')
#     def object_link(self, obj):
#         obj = obj.content_type.get_object_for_this_type(pk=obj.object_id)
#         return format_html('<a href="/admin/{}/{}/{}/change"><b>[{}]</b></a>', obj._meta.app_label, obj._meta.model_name, obj.pk, str(obj))

    
class TagAdmin(ABIDModelAdmin):
    list_display = ('created_at', 'created_by', 'abid', 'name', 'num_snapshots', 'snapshots')
    list_filter = ('created_at', 'created_by')
    sort_fields = ('name', 'slug', 'abid', 'created_by', 'created_at')
    readonly_fields = ('slug', 'abid', 'created_at', 'modified_at', 'abid_info', 'snapshots')
    search_fields = ('abid', 'name', 'slug')
    fields = ('name', 'created_by', *readonly_fields)
    actions = ['delete_selected', 'merge_tags']
    ordering = ['-created_at']
    # inlines = [TaggedItemInline]

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

    # def get_urls(self):
    #     urls = super().get_urls()
    #     custom_urls = [
    #         path(
    #             "merge-tags/",
    #             self.admin_site.admin_view(self.merge_tags_view),
    #             name="taggit_tag_merge_tags",
    #         ),
    #     ]
    #     return custom_urls + urls

    # @admin.action(description="Merge selected tags")
    # def merge_tags(self, request, queryset):
    #     selected = request.POST.getlist(admin.helpers.ACTION_CHECKBOX_NAME)
    #     if not selected:
    #         self.message_user(request, "Please select at least one tag.")
    #         return redirect(request.get_full_path())

    #     selected_tag_ids = ",".join(selected)
    #     redirect_url = f"{request.get_full_path()}merge-tags/"

    #     request.session["selected_tag_ids"] = selected_tag_ids

    #     return redirect(redirect_url)

    # def merge_tags_view(self, request):
    #     selected_tag_ids = request.session.get("selected_tag_ids", "").split(",")
    #     if request.method == "POST":
    #         form = MergeTagsForm(request.POST)
    #         if form.is_valid():
    #             new_tag_name = form.cleaned_data["new_tag_name"]
    #             new_tag, created = Tag.objects.get_or_create(name=new_tag_name)
    #             with transaction.atomic():
    #                 for tag_id in selected_tag_ids:
    #                     tag = Tag.objects.get(id=tag_id)
    #                     tagged_items = TaggedItem.objects.filter(tag=tag)
    #                     for tagged_item in tagged_items:
    #                         if TaggedItem.objects.filter(
    #                             tag=new_tag,
    #                             content_type=tagged_item.content_type,
    #                             object_id=tagged_item.object_id,
    #                         ).exists():
    #                             # we have the new tag as well, so we can just
    #                             # remove the tag association
    #                             tagged_item.delete()
    #                         else:
    #                             # point this taggedItem to the new one
    #                             tagged_item.tag = new_tag
    #                             tagged_item.save()
                        
    #                     # delete the old tag
    #                     if tag.id != new_tag.id:
    #                         tag.delete()

    #             self.message_user(request, "Tags have been merged", level="success")
    #             # clear the selected_tag_ids from session after merge is complete
    #             request.session.pop("selected_tag_ids", None)

    #             return redirect("..")
    #         else:
    #             self.message_user(request, "Form is invalid.", level="error")

    #     context = {
    #         "form": MergeTagsForm(),
    #         "selected_tag_ids": selected_tag_ids,
    #     }
    #     return render(request, "admin/taggit/merge_tags_form.html", context)


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

