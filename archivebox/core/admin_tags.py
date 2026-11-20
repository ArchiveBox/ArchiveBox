__package__ = "archivebox.core"

from copy import copy
from dataclasses import replace
from functools import partial
from urllib.parse import quote

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import ActionLocation, IS_POPUP_VAR
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpRequest, HttpResponseRedirect, QueryDict
from django.db.models import CharField, Prefetch
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from archivebox.base_models.admin import BaseModelAdmin
from archivebox.core.admin_snapshots import SnapshotActionForm
from archivebox.core.models import ArchiveResult, Folder, Snapshot, SnapshotTag, Tag
from archivebox.core.smart_folders import CHILDREN_RULES
from archivebox.core.widgets import TagEditorWidget
from archivebox.core.tag_util import annotate_tag_snapshot_counts, build_tag_cards
from archivebox.core.routes_util import build_snapshot_export_urls, build_snapshot_role_output_url
from archivebox.plugins.discovery import get_snapshot_role_names


class TagInline(admin.TabularInline):
    model = SnapshotTag
    fields = ("id", "tag")
    extra = 1
    max_num = 1000
    autocomplete_fields = ("tag",)


class TagAdminForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = "__all__"
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "research, receipts, product-design...",
                    "autocomplete": "off",
                    "spellcheck": "false",
                    "data-tag-name-input": "1",
                },
            ),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Tag name is required.")
        return name


TAGGED_SNAPSHOT_DELETE = "delete_tagged_snapshots"
TAG_SNAPSHOT_ACTIONS = frozenset(
    {
        "move_to_folder",
        "resnapshot_snapshot",
        "update_snapshots",
        "overwrite_snapshots",
        "set_snapshot_permissions",
    },
)


class TagAdmin(BaseModelAdmin):
    form = TagAdminForm
    change_list_template = "admin/core/tag/native_change_list.html"
    change_form_template = "admin/core/tag/change_form.html"
    list_display = ("name", "num_snapshots", "created_at", "created_by")
    list_filter = ("created_at", "created_by")
    search_fields = ("id", "name")
    readonly_fields = ("id", "created_at", "modified_at", "snapshots")
    actions = ["delete_selected"]
    action_form = SnapshotActionForm
    ordering = ["name", "id"]

    fieldsets = (
        (
            "Tag",
            {
                "fields": ("name",),
                "classes": ("card",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("id", "created_by", "created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
        (
            "Recent Snapshots",
            {
                "fields": ("snapshots",),
                "classes": ("card", "wide"),
            },
        ),
    )

    add_fieldsets = (
        (
            "Tag",
            {
                "fields": ("name",),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by",),
                "classes": ("card",),
            },
        ),
    )

    def get_fieldsets(self, request: HttpRequest, obj: Tag | None = None):
        return self.fieldsets if obj else self.add_fieldsets

    def get_changelist_instance(self, request):
        changelist = super().get_changelist_instance(request)
        if not changelist.is_popup and self.has_add_permission(request):
            changelist.inline_tag_create = TagEditorWidget(
                create_redirect=reverse("admin:core_tag_changelist"),
            ).render("tag_list_create", None)
        return changelist

    def get_queryset(self, request):
        return annotate_tag_snapshot_counts(super().get_queryset(request))

    def _snapshot_admin(self):
        return self.admin_site._registry.get(Snapshot)

    def _snapshot_actions(self, request):
        snapshot_admin = self._snapshot_admin()
        if not snapshot_admin or not snapshot_admin.has_view_or_change_permission(request):
            return {}
        return {
            (TAGGED_SNAPSHOT_DELETE if name == "delete_selected" else name): action
            for name, action in snapshot_admin.get_actions(request).items()
            if name == "delete_selected" or (name in TAG_SNAPSHOT_ACTIONS and snapshot_admin.has_change_permission(request))
        }

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        actions = super().get_actions(request, action_location=action_location)
        if action_location != ActionLocation.CHANGE_LIST or IS_POPUP_VAR in request.GET:
            return actions
        for name, action in self._snapshot_actions(request).items():
            actions[name] = replace(action, name=name, func=partial(TagAdmin._apply_snapshot_action, name=name))
        return actions

    def _apply_snapshot_action(self, request, tags, *, name):
        action = self._snapshot_actions(request).get(name)
        if action is None:
            raise PermissionDenied
        snapshot_admin = copy(self._snapshot_admin())
        snapshot_request = copy(request)
        # Tag search, pagination and ordering are not Snapshot filters.
        snapshot_request.GET = QueryDict()
        tag_ids = tags.order_by()
        if connection.vendor == "sqlite":
            # Keep legacy text tag IDs indexed, as in the tag count helpers.
            tag_ids = tag_ids.annotate(membership_id=Cast("pk", output_field=CharField())).values("membership_id")
        else:
            tag_ids = tag_ids.values("pk")
        membership = SnapshotTag.objects.filter(tag_id__in=tag_ids).order_by().values("snapshot_id")
        snapshots = snapshot_admin.get_queryset(snapshot_request).defer(None).filter(pk__in=membership)
        if name == TAGGED_SNAPSHOT_DELETE:
            return snapshot_admin.delete_selected(
                request,
                snapshots,
                confirmation_action=name,
                confirmation_selected=request.POST.getlist(ACTION_CHECKBOX_NAME),
                confirmation_across=request.POST.get("select_across") == "1",
            )
        if not snapshots.exists():
            self.message_user(request, "No snapshots match the selected tags.", level=messages.INFO)
            return None
        return action.func(snapshot_admin, request, snapshots)

    def changelist_view(self, request, extra_context=None):
        choices = self.get_action_choices(request)
        snapshot_choices = [(name, label) for name, label in choices if name in TAG_SNAPSHOT_ACTIONS or name == TAGGED_SNAPSHOT_DELETE]
        if snapshot_choices:
            context = {
                "snapshot_action_choices": snapshot_choices,
                "tag_action_choices": [
                    (name, label) for name, label in choices if name and name not in TAG_SNAPSHOT_ACTIONS and name != TAGGED_SNAPSHOT_DELETE
                ],
            }
            if any(name == "move_to_folder" for name, _ in snapshot_choices):
                context["move_folder_choices"] = Folder.path_choices(
                    folder for folder in Folder.tree() if folder.rules is None or folder.rules == CHILDREN_RULES
                )
            extra_context = {**(extra_context or {}), **context}
        return super().changelist_view(request, extra_context=extra_context)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        current_name = (request.POST.get("name") or "").strip()
        if not current_name and obj:
            current_name = obj.name

        similar_tag_cards = (
            build_tag_cards(query=current_name, request=request, limit=12, preview_limit=0)
            if current_name
            else build_tag_cards(request=request, limit=12, preview_limit=0)
        )
        if obj:
            similar_tag_cards = [card for card in similar_tag_cards if card["id"] != obj.pk]

        context.update(
            {
                "tag_search_api_url": reverse("api-1:search_tags"),
                "tag_similar_cards": similar_tag_cards,
                "tag_similar_query": current_name,
                "snapshot_export_urls": build_snapshot_export_urls({"tag": obj.pk}) if obj else {},
            },
        )
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def response_add(self, request: HttpRequest, obj: Tag, post_url_continue=None):
        if IS_POPUP_VAR in request.POST or "_continue" in request.POST or "_addanother" in request.POST:
            return super().response_add(request, obj, post_url_continue=post_url_continue)

        self.message_user(request, f'Tag "{obj.name}" saved.', level=messages.SUCCESS)
        return self._redirect_to_changelist(obj.name)

    def response_change(self, request: HttpRequest, obj: Tag):
        if IS_POPUP_VAR in request.POST or "_continue" in request.POST or "_addanother" in request.POST or "_saveasnew" in request.POST:
            return super().response_change(request, obj)

        self.message_user(request, f'Tag "{obj.name}" updated.', level=messages.SUCCESS)
        return self._redirect_to_changelist(obj.name)

    def _redirect_to_changelist(self, query: str = "") -> HttpResponseRedirect:
        changelist_url = reverse("admin:core_tag_changelist")
        if query:
            changelist_url = f"{changelist_url}?q={quote(query)}"
        return HttpResponseRedirect(changelist_url)

    @admin.display(description="Snapshots")
    def snapshots(self, tag: Tag):
        snapshots = (
            tag.snapshot_set.select_related("crawl__created_by")
            .prefetch_related(
                Prefetch(
                    "archiveresult_set",
                    queryset=ArchiveResult.objects.filter(
                        plugin__in=get_snapshot_role_names("list_icon"),
                        status=ArchiveResult.StatusChoices.SUCCEEDED,
                    ).only(
                        "snapshot_id",
                        "plugin",
                        "status",
                        "output_str",
                        "output_files",
                    ),
                    to_attr="_list_icon_results",
                ),
            )
            .order_by("-downloaded_at", "-created_at", "-pk")[:10]
        )
        total_count = tag.snapshot_set.count()
        if not snapshots:
            return mark_safe(
                f'<p style="margin:0;color:#64748b;">No snapshots use this tag yet. '
                f'<a href="/admin/core/snapshot/?tags__id__exact={tag.id}">Open filtered snapshot list</a>.</p>',
            )

        cards = []
        for snapshot in snapshots:
            title = (snapshot.title or "").strip() or snapshot.url
            cards.append(
                format_html(
                    """
                <a href="{}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;text-decoration:none;color:#0f172a;">
                    <img src="{}" alt="" style="width:18px;height:18px;border-radius:4px;flex:0 0 auto;" onerror="this.style.display='none'">
                    <span style="min-width:0;">
                        <strong style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{}</strong>
                        <code style="display:block;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{}</code>
                    </span>
                </a>
                """,
                    reverse("admin:core_snapshot_change", args=[snapshot.pk]),
                    build_snapshot_role_output_url(
                        snapshot,
                        "list_icon",
                        archive_results=snapshot._list_icon_results,
                        fallback_to_default=True,
                    ),
                    title[:120],
                    snapshot.url[:120],
                ),
            )

        cards.append(
            format_html(
                '<a href="/admin/core/snapshot/?tags__id__exact={}" style="display:inline-flex;margin-top:10px;font-weight:600;">View all {} tagged snapshots</a>',
                tag.id,
                total_count,
            ),
        )
        return mark_safe('<div style="display:grid;gap:10px;">' + "".join(cards) + "</div>")

    @admin.display(description="Snapshots", ordering="num_snapshots")
    def num_snapshots(self, tag: Tag):
        count = tag.__dict__.get("num_snapshots")
        if count is None:
            count = tag.snapshot_set.count()
        return format_html(
            '<a href="/admin/core/snapshot/?tags__id__exact={}">{} total</a>',
            tag.id,
            count,
        )


def register_admin(admin_site):
    admin_site.register(Tag, TagAdmin)
