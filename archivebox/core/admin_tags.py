__package__ = "archivebox.core"

from copy import copy
from dataclasses import replace
from functools import partial
from urllib.parse import quote

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import ActionLocation, IS_POPUP_VAR, TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, connection, router, transaction
from django.http import HttpRequest, HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse, QueryDict
from django.db.models import CharField, Prefetch
from django.db.models.functions import Cast
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from archivebox.base_models.admin import BaseModelAdmin
from archivebox.core.admin_snapshots import SnapshotActionForm
from archivebox.core.models import ArchiveResult, Snapshot, SnapshotTag, Tag
from archivebox.core.tag_merge import MERGE_MAX_TAGS, merge_selected_tags
from archivebox.core.widgets import TagEditorWidget
from archivebox.core.tag_util import annotate_tag_snapshot_counts, build_tag_cards, rename_tag
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
    actions = ["delete_selected", "merge_tags"]
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

    class Media:
        css = {"all": ("admin-tag-rename.css",)}
        js = ("admin-tag-rename.js",)

    def get_urls(self):
        return [
            path("<int:tag_id>/rename/", self.admin_site.admin_view(self.rename_tag), name="core_tag_rename"),
            *super().get_urls(),
        ]

    def get_list_display(self, request):
        fields = super().get_list_display(request)
        if IS_POPUP_VAR in request.GET or not self.has_change_permission(request):
            return fields

        @admin.display(description="Name", ordering="name")
        def name(tag):
            change_url = reverse("admin:core_tag_change", args=[tag.pk])
            if not self.has_change_permission(request, tag):
                return format_html('<a href="{}">{}</a>', change_url, tag.name)
            return format_html(
                '<span class="tag-inline-cell" data-tag-rename-url="{}">'
                '<a class="tag-inline-name" href="{}">{}</a>'
                '<button type="button" class="tag-inline-pencil" aria-label="Rename tag {}" title="Rename tag">'
                '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="m15 5 4 4M4 20l4.5-1 11-11a2.8 2.8 0 0 0-4-4l-11 11L4 20Z"/></svg></button>'
                '<input class="tag-inline-input" type="text" maxlength="{}" aria-label="Tag name" autocomplete="off" hidden>'
                '<span class="tag-inline-error" role="alert" hidden></span></span>',
                reverse("admin:core_tag_rename", args=[tag.pk]),
                change_url,
                tag.name,
                tag.name,
                Tag._meta.get_field("name").max_length,
            )

        return tuple(name if field == "name" else field for field in fields)

    def get_list_display_links(self, request, list_display):
        # The editable name column already owns its link and adjacent button.
        if any(callable(field) and field.__name__ == "name" for field in list_display):
            return None
        return super().get_list_display_links(request, list_display)

    def rename_tag(self, request, tag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        tag = self.get_object(request, str(tag_id))
        if tag is None:
            return JsonResponse({"error": "Tag not found."}, status=404)
        if not self.has_change_permission(request, tag):
            raise PermissionDenied

        try:
            name = forms.CharField(max_length=Tag._meta.get_field("name").max_length).clean(request.POST.get("name"))
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)

        original_name = tag.name
        try:
            rename_tag(tag, name)
        except ValueError as error:
            return JsonResponse({"error": str(error)}, status=400)
        if tag.name != original_name:
            self.log_change(request, tag, [{"changed": {"fields": ["name"]}}])
        return JsonResponse({"name": tag.name})

    def _can_delete_tags(self, request, tags):
        _, _, perms_needed, protected = self.get_deleted_objects(tags, request)
        if perms_needed:
            raise PermissionDenied
        if protected:
            self.message_user(request, "The selected tags are still in use by protected records.", level=messages.ERROR)
        return not protected

    def delete_view(self, request, object_id, extra_context=None):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        wants_json = request.headers.get("Accept") == "application/json"
        to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
        if to_field and not self.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField(f"The field {to_field} cannot be referenced.")
        with transaction.atomic(using=router.db_for_write(self.model)):
            tag = self.get_object(request, unquote(object_id), to_field)
            if not self.has_delete_permission(request, tag):
                raise PermissionDenied
            if tag is None:
                if wants_json:
                    return JsonResponse({"error": "Tag not found."}, status=404)
                return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)
            if not self._can_delete_tags(request, [tag]):
                if wants_json:
                    return JsonResponse({"error": "The tag is still in use by protected records."}, status=409)
                return self._redirect_to_changelist()
            tag_pk = tag.pk
            obj_id = tag.serializable_value(to_field or self.opts.pk.attname)
            name = str(tag)
            self.log_deletions(request, [tag])
            self.delete_model(request, tag)

        if wants_json:
            return JsonResponse({"deleted": True})
        response = self.response_delete(request, name, obj_id)
        path, _, query = request.POST.get("return_to", "").partition("?")
        if IS_POPUP_VAR in request.POST:
            return response
        if path in {reverse("admin:core_snapshot_changelist"), reverse("admin:grid")}:
            filters = QueryDict(query, mutable=True)
            for key in ("tag", "tags__id__exact"):
                if filters.get(key) == str(tag_pk):
                    filters.pop(key)
                    filters.pop("p", None)
            return HttpResponseRedirect(f"{path}?{filters.urlencode()}" if filters else path)
        if not self.has_change_permission(request) and self.has_view_permission(request):
            return self._redirect_to_changelist()
        return response

    @admin.action(permissions=["delete"], description="Delete selected tags")
    def delete_selected(self, request, queryset):
        with transaction.atomic(using=queryset.db):
            count = len(queryset)
            if count and self._can_delete_tags(request, queryset):
                self.log_deletions(request, queryset)
                self.delete_queryset(request, queryset)
                self.message_user(request, f"Deleted {count} {'tag' if count == 1 else 'tags'}.", level=messages.SUCCESS)

    def get_fieldsets(self, request: HttpRequest, obj: Tag | None = None):
        return self.fieldsets if obj else self.add_fieldsets

    def get_changelist_instance(self, request):
        changelist = super().get_changelist_instance(request)
        if not changelist.is_popup and self.has_add_permission(request):
            changelist.inline_tag_create = TagEditorWidget(
                create_redirect=reverse("admin:core_tag_changelist"),
            ).render("tag_list_create", None)
        if not changelist.is_popup and self.has_merge_permission(request):
            changelist.merge_max_tags = MERGE_MAX_TAGS
        return changelist

    def get_queryset(self, request):
        return annotate_tag_snapshot_counts(super().get_queryset(request))

    def has_merge_permission(self, request):
        snapshot_admin = self._snapshot_admin()
        return bool(
            self.has_change_permission(request)
            and self.has_delete_permission(request)
            and snapshot_admin
            and snapshot_admin.has_change_permission(request),
        )

    @admin.action(permissions=["merge"], description="Merge Tags")
    def merge_tags(self, request, tags):
        if not self.has_merge_permission(request):
            raise PermissionDenied
        if any(value not in {"", "0"} for value in request.POST.getlist("select_across")):
            self.message_user(
                request,
                "Select the individual tags to merge. Select all matching tags is not supported.",
                level=messages.ERROR,
            )
            return None
        if request.POST.get("confirm_tag_merge") != "1":
            self.message_user(request, "Confirm which tags to merge before continuing.", level=messages.ERROR)
            return None
        # The merge is all-or-nothing across each selected tag. If any linked
        # Snapshot is outside this staff member's admin scope, refuse the action.
        snapshot_admin = copy(self._snapshot_admin())
        snapshot_request = copy(request)
        snapshot_request.GET = QueryDict()
        snapshot_scope = snapshot_admin.get_queryset(snapshot_request)
        try:
            target, retired, snapshots = merge_selected_tags(
                tags,
                request.POST.get("merge_tag_name", ""),
                user=request.user,
                can_create=self.has_add_permission(request),
                selected_count=request.POST.get("confirm_tag_merge_count"),
                snapshot_scope=snapshot_scope,
            )
        except ValueError as err:
            self.message_user(request, str(err), level=messages.ERROR)
            return None
        except OperationalError as err:
            if connection.vendor != "sqlite" or "locked" not in str(err).lower():
                raise
            self.message_user(
                request,
                "The database was busy. No tags were merged. Try again after active writes finish.",
                level=messages.ERROR,
            )
            return None
        self.message_user(
            request,
            f'Merged into "{target.name}": retired {retired} tag(s); retained {snapshots} Snapshot(s).',
            level=messages.SUCCESS,
        )
        return self._redirect_to_changelist(target.name)

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
        if snapshot_choices or self.has_merge_permission(request):
            context = {
                "snapshot_action_choices": snapshot_choices,
                "tag_action_choices": [
                    (name, label) for name, label in choices if name and name not in TAG_SNAPSHOT_ACTIONS and name != TAGGED_SNAPSHOT_DELETE
                ],
            }
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
                "delete_with_post": True,
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
