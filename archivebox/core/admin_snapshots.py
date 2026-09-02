__package__ = "archivebox.core"

import json
from functools import lru_cache
from types import SimpleNamespace

from django.contrib import admin, messages
from django.urls import path, reverse
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.db.models import Q, Count, Exists, F, OuterRef, Prefetch
from django import forms
from django.template import Template, RequestContext
from django.contrib.admin.helpers import ActionForm

from archivebox.config.common import get_config
from archivebox.misc.util import htmldecode, urldecode
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.misc.logging_util import printable_filesize
from archivebox.search.admin import SearchResultsAdminMixin, SearchResultsChangeList
from archivebox.search.views import admin_snapshot_search_stream_view
from archivebox.core.routes_util import build_snapshot_url, build_web_url
from archivebox.core.tag_util import get_or_create_tag
from archivebox.plugins.hooks import discover_hooks
from archivebox.plugins.discovery import get_plugin_icon, get_plugin_name, get_plugins

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from archivebox.core.models import Tag, Snapshot, ArchiveResult
from archivebox.crawls.models import Crawl
from archivebox.core.admin_archiveresults import render_archiveresults_list
from archivebox.core.preview_util import EXTENSION_SCREENSHOT_PLUGIN
from archivebox.progressmonitor.views import progress_endpoint
from archivebox.core.permissions import (
    PERMISSIONS_CHOICES,
    PERMISSIONS_META,
    get_snapshot_permissions,
    normalize_permissions,
)
from archivebox.core.widgets import TagEditorWidget, InlineTagEditorWidget


GLOBAL_CONTEXT = {}

SNAPSHOT_PERMISSION_META = PERMISSIONS_META


@lru_cache(maxsize=1)
def _plugin_sort_order() -> dict[str, int]:
    return {get_plugin_name(plugin): idx for idx, plugin in enumerate(get_plugins())}


class SnapshotActionForm(ActionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define tags field in __init__ to avoid database access during app initialization
        self.fields["tags"] = forms.CharField(
            label="",
            required=False,
            widget=TagEditorWidget(),
        )

    def clean_tags(self):
        """Parse comma-separated tag names without touching the DB."""
        tags_str = self.cleaned_data.get("tags", "")
        if not tags_str:
            return []

        return [name.strip() for name in tags_str.split(",") if name.strip()]


class TagNameListFilter(admin.SimpleListFilter):
    title = "By tag name"
    parameter_name = "tag"

    def lookups(self, request, model_admin):
        selected = self.value()
        tags = list(Tag.objects.order_by("name").only("id", "name")[:100])
        if selected and selected.isdigit() and all(str(tag.pk) != selected for tag in tags):
            selected_tag = Tag.objects.filter(pk=int(selected)).only("id", "name").first()
            if selected_tag:
                tags.insert(0, selected_tag)
        return [(str(tag.pk), tag.name) for tag in tags]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(tags__id=self.value())
        return queryset


class SnapshotPermissionsListFilter(admin.SimpleListFilter):
    title = "permission"
    parameter_name = "permissions"

    def lookups(self, request, model_admin):
        return PERMISSIONS_CHOICES

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            return queryset.filter(permissions=value)
        return queryset


class SnapshotStatusListFilter(admin.SimpleListFilter):
    title = "snapshot status"
    parameter_name = "snapshot_status"

    def lookups(self, request, model_admin):
        return Snapshot.StatusChoices.choices

    def queryset(self, request, queryset):
        value = self.value()
        if value in Snapshot.StatusChoices.values:
            return queryset.filter(status=value)
        return queryset


class SnapshotArchiveStateListFilter(admin.SimpleListFilter):
    title = "archive state"
    parameter_name = "archive_state"

    def lookups(self, request, model_admin):
        return (
            ("downloaded", "Downloaded"),
            ("not_downloaded", "Not downloaded"),
            ("has_output", "Has saved files"),
            ("empty_output", "No saved files"),
            ("has_title", "Has title"),
            ("missing_title", "Missing title"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "downloaded":
            return queryset.filter(downloaded_at__isnull=False)
        if value == "not_downloaded":
            return queryset.filter(downloaded_at__isnull=True)
        if value == "has_output":
            return queryset.filter(output_size__gt=0)
        if value == "empty_output":
            return queryset.filter(output_size=0)
        if value == "has_title":
            return queryset.exclude(Q(title__isnull=True) | Q(title=""))
        if value == "missing_title":
            return queryset.filter(Q(title__isnull=True) | Q(title=""))
        return queryset


class SnapshotSizeListFilter(admin.SimpleListFilter):
    title = "size"
    parameter_name = "size"

    def lookups(self, request, model_admin):
        return (
            ("1gb", ">1GB"),
            ("500mb", ">500MB"),
            ("250mb", ">250MB"),
            ("100mb", ">100MB"),
            ("50mb", ">50MB"),
            ("25mb", ">25MB"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        thresholds = {
            "1gb": 1024 * 1024 * 1024,
            "500mb": 500 * 1024 * 1024,
            "250mb": 250 * 1024 * 1024,
            "100mb": 100 * 1024 * 1024,
            "50mb": 50 * 1024 * 1024,
            "25mb": 25 * 1024 * 1024,
        }
        if value in thresholds:
            return queryset.filter(output_size__gt=thresholds[value])
        return queryset


class SnapshotResultHealthListFilter(admin.SimpleListFilter):
    title = "ArchiveResult status"
    parameter_name = "archiveresult_status"
    SNAPSHOT_FIRST_VALUES = {"succeeded"}

    def lookups(self, request, model_admin):
        return (
            ("none", "No ArchiveResults"),
            ("has_results", "Has ArchiveResults"),
            ("succeeded", ">50% succeeded"),
            ("failed", ">50% failed"),
            ("running", ">50% running"),
            ("pending", ">50% queued"),
            ("noresults", ">50% noresults"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk"))
            if value == "none":
                return queryset.annotate(has_results=Exists(results)).filter(has_results=False)
            if value == "has_results":
                return queryset.annotate(has_results=Exists(results)).filter(has_results=True)
            status_by_value = {
                "succeeded": ArchiveResult.StatusChoices.SUCCEEDED,
                "failed": ArchiveResult.StatusChoices.FAILED,
                "running": ArchiveResult.StatusChoices.STARTED,
                "pending": (ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.BACKOFF),
                "backoff": ArchiveResult.StatusChoices.BACKOFF,
                "noresults": ArchiveResult.StatusChoices.NORESULTS,
            }
            if value in status_by_value:
                status = status_by_value[value]
                if value in self.SNAPSHOT_FIRST_VALUES:
                    # "succeeded" is overwhelmingly common in large collections.
                    # Scan Snapshots in admin order and do indexed per-snapshot
                    # probes so page 1 can stop after list_per_page matches.
                    queryset = queryset.alias(
                        total_results=ArchiveResult.snapshot_count_expr(),
                        matching_results=ArchiveResult.snapshot_count_expr(status=status),
                    ).filter(matching_results__gt=F("total_results") / 2)
                    return queryset

                # Rare statuses are faster status-first: use the
                # (status, snapshot_id) index to find candidate snapshots.
                return queryset.filter(pk__in=ArchiveResult.snapshot_ids_with_majority_status(status))
        return queryset


class SnapshotChangeList(SearchResultsChangeList):
    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        resolver_name = request.resolver_match.url_name
        self.embedded_changelist = request.GET.get("_embedded") == "crawl"
        self.snapshot_is_grid_view = not self.embedded_changelist and (
            resolver_name == "grid" or request.path.rstrip("/").endswith("/grid")
        )

    def _attach_archiveresult_summaries(self):
        snapshot_ids = [obj.pk for obj in self.result_list]
        if not snapshot_ids:
            return

        status_counts_by_snapshot = {
            row["snapshot_id"]: row
            for row in ArchiveResult.objects.filter(snapshot_id__in=snapshot_ids)
            .values("snapshot_id")
            .annotate(
                total=Count("pk"),
                succeeded=Count("pk", filter=Q(status=ArchiveResult.StatusChoices.SUCCEEDED)),
                failed=Count("pk", filter=Q(status=ArchiveResult.StatusChoices.FAILED)),
                running=Count("pk", filter=Q(status=ArchiveResult.StatusChoices.STARTED)),
                skipped=Count("pk", filter=Q(status=ArchiveResult.StatusChoices.SKIPPED)),
                noresults=Count("pk", filter=Q(status=ArchiveResult.StatusChoices.NORESULTS)),
            )
        }

        output_results_by_snapshot = {snapshot_id: [] for snapshot_id in snapshot_ids}
        seen_plugins = {snapshot_id: set() for snapshot_id in snapshot_ids}
        rows = (
            ArchiveResult.objects.filter(snapshot_id__in=snapshot_ids, status=ArchiveResult.StatusChoices.SUCCEEDED, output_size__gt=0)
            .order_by("snapshot_id", "plugin")
            .values_list("snapshot_id", "plugin", "status", "output_size", "output_files")
        )
        for snapshot_id, plugin, status, output_size, output_files in rows.iterator(chunk_size=1000):
            if plugin in seen_plugins[snapshot_id]:
                continue
            seen_plugins[snapshot_id].add(plugin)
            output_results_by_snapshot[snapshot_id].append(
                SimpleNamespace(plugin=plugin, status=status, output_size=output_size, output_files=output_files),
            )

        for obj in self.result_list:
            counts = status_counts_by_snapshot.get(obj.pk, {})
            total = int(counts.get("total") or 0)
            succeeded = int(counts.get("succeeded") or 0)
            failed = int(counts.get("failed") or 0)
            running = int(counts.get("running") or 0)
            skipped = int(counts.get("skipped") or 0)
            noresults = int(counts.get("noresults") or 0)
            completed = succeeded + failed + skipped + noresults
            obj.__dict__["_admin_progress_stats"] = {
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "running": running,
                "pending": max(total - completed - running, 0),
                "skipped": skipped,
                "noresults": noresults,
                "percent": int((completed / total * 100) if total else 0),
                "output_size": obj.output_size or 0,
                "is_sealed": obj.status not in (obj.StatusChoices.QUEUED, obj.StatusChoices.STARTED, obj.StatusChoices.PAUSED),
            }
            obj.__dict__["_admin_output_results"] = output_results_by_snapshot[obj.pk]

    def get_results(self, request):
        super().get_results(request)
        if request.GET.get("_embedded") == "crawl":
            self.full_result_count = self.result_count
            self.show_full_result_count = True
        self._attach_archiveresult_summaries()


class SnapshotAdminForm(forms.ModelForm):
    """Custom form for Snapshot admin with tag editor widget."""

    tags_editor = forms.CharField(
        label="Tags",
        required=False,
        widget=TagEditorWidget(),
        help_text="Type tag names and press Enter or Space to add. Click × to remove.",
    )
    permissions_config = forms.ChoiceField(
        label="Permissions",
        choices=PERMISSIONS_CHOICES,
        required=True,
        help_text="Per-snapshot visibility. Matching the crawl/persona default clears the per-snapshot override.",
    )

    class Meta:
        model = Snapshot
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize tags_editor with current tags
        if self.instance and self.instance.pk:
            self.initial["tags_editor"] = ",".join(
                sorted(tag.name for tag in self.instance.tags.all()),
            )
            self.initial["permissions_config"] = get_snapshot_permissions(self.instance)

    def save(self, commit=True):
        instance = super().save(commit=False)
        permissions = self.cleaned_data["permissions_config"]
        config = dict(instance.config or {})
        config["PERMISSIONS"] = permissions
        instance.config = config

        # Handle tags_editor field
        if commit:
            instance.save()
            self._save_m2m()

            # Parse and save tags from tags_editor
            tags_str = self.cleaned_data.get("tags_editor", "")
            tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
            instance.save_tags(tag_names)

        return instance


class SnapshotAdmin(SearchResultsAdminMixin, ConfigEditorMixin, BaseModelAdmin):
    form = SnapshotAdminForm
    raw_id_fields = ("crawl", "parent_snapshot")
    list_select_related = ()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        tags_str = form.cleaned_data.get("tags_editor", "")
        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        form.instance.save_tags(
            tag_names,
            created_by=request.user if request.user.is_authenticated else None,
        )

    list_display = (
        "permissions_badge",
        "created_at",
        "preview_icon",
        "title_str",
        "tags_inline",
        "status_with_progress",
        "files",
        "size_with_stats",
    )
    list_display_links = ("created_at",)
    sort_fields = ("title_str", "created_at", "status", "crawl")
    readonly_fields = (
        "admin_actions",
        "snapshot_summary",
        "url_favicon",
        "tags_badges",
        "imported_timestamp",
        "created_at",
        "modified_at",
        "downloaded_at",
        "output_dir",
        "archiveresults_list",
    )
    search_fields = ("id", "url", "timestamp", "title", "tags__name")
    list_filter = (
        SnapshotPermissionsListFilter,
        SnapshotStatusListFilter,
        SnapshotResultHealthListFilter,
        SnapshotArchiveStateListFilter,
        SnapshotSizeListFilter,
        "created_at",
        "downloaded_at",
        "crawl__created_by",
        TagNameListFilter,
    )

    fieldsets = (
        (
            "Actions",
            {
                "fields": ("admin_actions",),
                "classes": ("card", "actions-card"),
            },
        ),
        (
            "Snapshot",
            {
                "fields": ("snapshot_summary",),
                "classes": ("card",),
            },
        ),
        (
            "URL",
            {
                "fields": (("url_favicon", "url"), ("title", "tags_badges")),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Tags",
            {
                "fields": ("tags_editor", "permissions_config"),
                "classes": ("card",),
            },
        ),
        (
            "Status",
            {
                "fields": ("status", "retry_at"),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("bookmarked_at", "created_at", "modified_at", "downloaded_at"),
                "classes": ("card",),
            },
        ),
        (
            "Relations",
            {
                "fields": ("crawl",),
                "classes": ("card",),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "description": '<span style="display:block; margin:-4px 0 6px; font-size:11px; line-height:1.35; color:#94a3b8;">Uses <code>Crawl.config</code> by default. Only set per-snapshot overrides here when needed.</span>',
                "classes": ("card",),
            },
        ),
        (
            "Files",
            {
                "fields": ("output_dir",),
                "classes": ("card",),
            },
        ),
        (
            "Archive Results",
            {
                "fields": ("archiveresults_list",),
                "classes": ("card", "wide"),
            },
        ),
    )

    ordering = ["-created_at"]
    actions = [
        "add_tags",
        "remove_tags",
        "resnapshot_snapshot",
        "update_snapshots",
        "overwrite_snapshots",
        "set_snapshot_permissions",
        "delete_snapshots",
    ]
    inlines = []  # Removed TagInline, using TagEditorWidget instead
    list_per_page = 50

    action_form = SnapshotActionForm
    paginator = AcceleratedPaginator

    save_on_top = True
    show_full_result_count = True

    def get_changelist(self, request, **kwargs):
        return SnapshotChangeList

    def get_ordering(self, request):
        if request.GET.get("o"):
            return []
        return super().get_ordering(request)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        self.request = request
        context["CONFIG"] = request.archivebox_config
        if obj and obj.status in {
            Snapshot.StatusChoices.QUEUED,
            Snapshot.StatusChoices.STARTED,
            Snapshot.StatusChoices.PAUSED,
        }:
            context["progress_auto_expand"] = True
            context["progress_endpoint"] = progress_endpoint("snapshot", obj.id)
        context.update(GLOBAL_CONTEXT)
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def changelist_view(self, request, extra_context=None):
        self.request = request
        saved_list_per_page = self.list_per_page
        embedded_changelist = request.GET.get("_embedded") == "crawl"
        if embedded_changelist:
            try:
                requested_per_page = int(request.GET.get("per_page", "200"))
            except ValueError:
                requested_per_page = 200
            self.list_per_page = min(max(200, requested_per_page), 500)
        else:
            self.list_per_page = request.archivebox_config.SNAPSHOTS_PER_PAGE
        extra_context = extra_context or {}
        extra_context["embedded_changelist"] = embedded_changelist
        extra_context["CONFIG"] = request.archivebox_config
        try:
            try:
                return super().changelist_view(request, extra_context | GLOBAL_CONTEXT)
            except Exception as e:
                self.message_user(request, f"Error occurred while loading the page: {str(e)} {request.GET} {request.POST}")
                return super().changelist_view(request, GLOBAL_CONTEXT)
        finally:
            self.list_per_page = saved_list_per_page

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not actions:
            return {}
        actions.pop("delete_selected", None)
        return actions

    def lookup_allowed(self, lookup, value, request=None):
        if lookup in {"crawl__id__exact", "crawl_id__exact", "crawl_id"}:
            return True
        return super().lookup_allowed(lookup, value, request=request)

    def get_snapshot_view_url(self, obj: Snapshot) -> str:
        request = self.request
        return build_snapshot_url(str(obj.id), request=request, config=request.archivebox_config)

    def get_snapshot_files_url(self, obj: Snapshot) -> str:
        request = self.request
        return f"{build_snapshot_url(str(obj.id), request=request, config=request.archivebox_config)}/?files=1"

    def get_snapshot_zip_url(self, obj: Snapshot) -> str:
        return f"{self.get_snapshot_files_url(obj)}&download=zip"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("grid/", self.admin_site.admin_view(self.grid_view), name="grid"),
            path("search-stream/", self.admin_site.admin_view(self.search_stream_view), name="core_snapshot_search_stream"),
            path("<path:object_id>/redo-failed/", self.admin_site.admin_view(self.redo_failed_view), name="core_snapshot_redo_failed"),
            path(
                "<path:object_id>/set-permissions/",
                self.admin_site.admin_view(self.set_permissions_view),
                name="core_snapshot_set_permissions",
            ),
        ]
        return custom_urls + urls

    def search_stream_view(self, request):
        return admin_snapshot_search_stream_view(self, request)

    def set_permissions_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in dict(PERMISSIONS_CHOICES):
            return HttpResponseBadRequest("Invalid permissions value")

        snapshot = get_object_or_404(Snapshot, pk=object_id)
        config = dict(snapshot.config or {})
        config["PERMISSIONS"] = permissions

        # Keep the quick-edit write to one targeted UPDATE so SQLite only holds
        # the write lock for the permission/config change itself. safe_update()
        # keeps this from overwriting a concurrent admin/runner edit to the
        # same Snapshot after the row was loaded above.
        snapshot.safe_update({"config": config, "modified_at": timezone.now()}, refresh=False)
        icon, label, fg, bg = SNAPSHOT_PERMISSION_META[permissions]
        return JsonResponse({"permissions": permissions, "icon": icon, "label": label, "fg": fg, "bg": bg})

    @admin.action(description="Permissions ▾")
    def set_snapshot_permissions(self, request, queryset):
        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in dict(PERMISSIONS_CHOICES):
            messages.error(request, "Choose a valid permissions value.")
            return
        updated = self.update_snapshot_permissions(queryset, permissions)
        messages.success(request, f"Set permissions to {permissions} on {updated} snapshot(s).")

    def update_snapshot_permissions(self, queryset, permissions):
        now = timezone.now()
        updated = 0
        batch = []
        snapshots = queryset.select_related(None).only("id", "config").prefetch_related(None)
        for snapshot in snapshots.iterator(chunk_size=500):
            config = dict(snapshot.config or {})
            config["PERMISSIONS"] = permissions
            snapshot.config = config
            snapshot.modified_at = now
            batch.append(snapshot)
            if len(batch) >= 500:
                Snapshot.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
                updated += len(batch)
                batch.clear()
        if batch:
            Snapshot.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
            updated += len(batch)
        return updated

    def redo_failed_view(self, request, object_id):
        snapshot = get_object_or_404(Snapshot, pk=object_id)

        if request.method == "POST":
            retried = snapshot.retry_failed_archiveresults()
            if retried:
                messages.success(
                    request,
                    f"Queued {retried} failed extractors for retry on this snapshot.",
                )
            else:
                messages.info(
                    request,
                    "No failed extractors were found on this snapshot.",
                )

        return redirect(snapshot.admin_change_url)

    def get_queryset(self, request):
        self.request = request
        ordering_fields = self._get_ordering_fields(request)
        needs_files_sort = "files" in ordering_fields
        needs_tags_sort = "tags_inline" in ordering_fields
        is_change_view = request.resolver_match.url_name == "core_snapshot_change"
        prefetches = ["tags"]
        if is_change_view:
            prefetches.append(
                Prefetch(
                    "archiveresult_set",
                    queryset=ArchiveResult.objects.only(
                        "id",
                        "snapshot_id",
                        "plugin",
                        "status",
                        "output_size",
                        "output_files",
                    ),
                ),
            )
        else:
            prefetches.append(
                Prefetch(
                    "crawl",
                    queryset=Crawl.objects.select_related("created_by").only(
                        "id",
                        "created_by_id",
                        "created_by__id",
                        "created_by__username",
                    ),
                ),
            )

        qs = super().get_queryset(request)
        if is_change_view:
            qs = qs.select_related("crawl__created_by").defer("notes")
        else:
            qs = qs.only(
                "id",
                "created_at",
                "url",
                "timestamp",
                "bookmarked_at",
                "crawl_id",
                "title",
                "status",
                "fs_version",
                "output_size",
                "permissions",
            )
        qs = qs.prefetch_related(*prefetches)
        if needs_files_sort:
            qs = qs.annotate(
                ar_succeeded_count=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED),
            )
        if needs_tags_sort:
            qs = qs.annotate(tag_count=Count("tags", distinct=True))

        return qs

    @admin.display(description="👁", ordering="permissions")
    def permissions_badge(self, obj):
        permissions = obj.__dict__.get("snapshot_permissions")
        if permissions is None:
            permissions = obj.permissions
        permissions = normalize_permissions(permissions)
        icon, label, fg, bg = SNAPSHOT_PERMISSION_META[permissions]
        menu_items = format_html_join(
            "",
            (
                '<button type="button" class="snapshot-permissions-menu-item{}" data-permissions="{}">'
                '<span class="snapshot-permissions-icon" aria-hidden="true" style="color:{}; background:{};">{}</span>'
                "<span>{}</span>"
                "</button>"
            ),
            (
                (
                    " is-active" if choice_value == permissions else "",
                    choice_value,
                    choice_fg,
                    choice_bg,
                    choice_icon,
                    choice_label,
                )
                for choice_value, choice_label in PERMISSIONS_CHOICES
                for choice_icon, _choice_title, choice_fg, choice_bg in [SNAPSHOT_PERMISSION_META[choice_value]]
            ),
        )
        return format_html(
            '<span class="snapshot-permissions-quick" data-current-permissions="{}" data-permissions-url="{}">'
            '<button type="button" class="snapshot-permissions-button snapshot-permissions-{}" title="{}" aria-label="Change snapshot permissions: {}" aria-expanded="false">'
            '<span class="snapshot-permissions-icon" aria-hidden="true" style="color:{}; background:{};">{}</span>'
            "</button>"
            '<span class="snapshot-permissions-menu" role="menu" hidden>{}</span>'
            "</span>",
            permissions,
            reverse(f"{self.admin_site.name}:core_snapshot_set_permissions", args=[obj.pk]),
            permissions,
            label,
            label,
            fg,
            bg,
            icon,
            menu_items,
        )

    @admin.display(description="Imported Timestamp")
    def imported_timestamp(self, obj):
        context = RequestContext(
            self.request,
            {
                "bookmarked_date": obj.bookmarked_at,
                "timestamp": obj.timestamp,
            },
        )

        html = Template("""{{bookmarked_date}} (<code>{{timestamp}}</code>)""")
        return mark_safe(html.render(context))

    @admin.display(description="")
    def admin_actions(self, obj):
        summary_url = self.get_snapshot_view_url(obj)
        files_url = self.get_snapshot_files_url(obj)
        zip_url = self.get_snapshot_zip_url(obj)
        redo_failed_url = f"/admin/core/snapshot/{obj.pk}/redo-failed/"
        return format_html(
            """
            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📄 View Snapshot
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📁 All files
                </a>
                <a class="btn archivebox-zip-button" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1d4ed8; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   data-loading-label="Preparing..."
                   onclick="return window.archiveboxHandleZipClick(this, event);"
                   onmouseover="this.style.background='#dbeafe'; this.style.borderColor='#93c5fd';"
                   onmouseout="this.style.background='#eff6ff'; this.style.borderColor='#bfdbfe';">
                    <span class="archivebox-zip-spinner" aria-hidden="true"></span>
                    <span class="archivebox-zip-label">⬇ Download Zip</span>
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="{}"
                   target="_blank"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    🔗 Original URL
                </a>

                <span style="border-left: 1px solid #e2e8f0; height: 24px; margin: 0 4px;"></span>

                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1e40af; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Create a fresh new snapshot of this URL"
                   onmouseover="this.style.background='#dbeafe';"
                   onmouseout="this.style.background='#eff6ff';">
                    🆕 Snapshot Again
                </a>
                <button type="submit"
                        formaction="{}"
                        formmethod="post"
                        formnovalidate
                        class="btn"
                        style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; color: #065f46; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s; cursor: pointer;"
                        title="Redo failed extractors (missing outputs)"
                        onmouseover="this.style.background='#d1fae5';"
                        onmouseout="this.style.background='#ecfdf5';">
                    🔁 Retry Failed Extractors
                </button>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; color: #92400e; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Re-run all extractors (overwrite existing)"
                   onmouseover="this.style.background='#fef3c7';"
                   onmouseout="this.style.background='#fffbeb';">
                    🔄 Reset &amp; Retry All Extractors
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; color: #991b1b; text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.15s;"
                   href="/admin/core/snapshot/?id__exact={}"
                   title="Permanently delete this snapshot"
                   onmouseover="this.style.background='#fee2e2';"
                   onmouseout="this.style.background='#fef2f2';">
                    ☠️ Delete
                </a>
            </div>
            """,
            summary_url,
            files_url,
            zip_url,
            obj.url,
            obj.pk,
            redo_failed_url,
            obj.pk,
            obj.pk,
        )

    def status_info(self, obj):
        request = self.request
        config = request.archivebox_config
        favicon_url = build_snapshot_url(str(obj.id), "favicon.ico", request=request, config=config)
        return format_html(
            """
            Archived: {} ({} files {}) &nbsp; &nbsp;
            Favicon: <img src="{}" style="height: 20px"/> &nbsp; &nbsp;
            Extension: {} &nbsp; &nbsp;
            """,
            "✅" if obj.is_archived else "❌",
            obj.num_outputs,
            self.size(obj) or "0kb",
            favicon_url,
            obj.extension or "-",
        )

    @admin.display(description="Archive Results")
    def archiveresults_list(self, obj):
        request = self.request
        return render_archiveresults_list(
            obj.archiveresult_set.all(),
            limit=8,
            config=request.archivebox_config,
            can_delete=request.user.is_superuser,
        )

    @admin.display(
        description="Title",
        ordering="title",
    )
    def title_str(self, obj):
        request = self.request
        config = request.archivebox_config
        title_raw = (obj.title or "").strip()
        url_raw = (obj.url or "").strip()
        title_normalized = title_raw.lower()
        url_normalized = url_raw.lower()
        show_title = bool(title_raw) and title_normalized != "pending..." and title_normalized != url_normalized
        css_class = "fetched" if show_title else "pending"

        detail_url = build_web_url(f"/{obj.archive_path_from_db}/index.html", request=request, config=config)
        title_html = ""
        if show_title:
            title_html = format_html(
                '<a href="{}"><b class="status-{}">{}</b></a>',
                detail_url,
                css_class,
                urldecode(htmldecode(title_raw))[:128],
            )

        return format_html(
            "{}"
            '<div style="font-size: 11px; color: #64748b; margin-top: 2px;">'
            '<a href="{}"><code style="user-select: all;">{}</code></a>'
            "</div>",
            title_html,
            url_raw or obj.url,
            (url_raw or obj.url)[:128],
        )

    @admin.display(description="Tags", ordering="tag_count")
    def tags_inline(self, obj):
        widget = InlineTagEditorWidget(snapshot_id=str(obj.pk), editable=True)
        tags = self._get_prefetched_tags(obj)
        tags_html = widget.render(
            name=f"tags_inline_{obj.pk}",
            value=tags if tags is not None else obj.tags.all(),
            attrs={"id": f"tags_inline_{obj.pk}"},
            snapshot_id=str(obj.pk),
        )
        return mark_safe(f'<span class="tags-inline-editor tags-inline-editor--compact">{tags_html}</span>')

    @admin.display(description="Tags")
    def tags_badges(self, obj):
        widget = InlineTagEditorWidget(snapshot_id=str(obj.pk), editable=False)
        tags = self._get_prefetched_tags(obj)
        tags_html = widget.render(
            name=f"tags_readonly_{obj.pk}",
            value=tags if tags is not None else obj.tags.all(),
            attrs={"id": f"tags_readonly_{obj.pk}"},
            snapshot_id=str(obj.pk),
        )
        return mark_safe(f'<span class="tags-inline-editor">{tags_html}</span>')

    def _get_preview_data(self, obj):
        request = self.request
        config = request.archivebox_config
        results = self._get_prefetched_results(obj)
        if results is not None:
            results = [r for r in results if r.plugin in ("screenshot", EXTENSION_SCREENSHOT_PLUGIN, "favicon")]
        else:
            results = list(
                obj.archiveresult_set.filter(plugin__in=("screenshot", EXTENSION_SCREENSHOT_PLUGIN, "favicon")).only(
                    "snapshot_id",
                    "plugin",
                    "status",
                    "output_files",
                    "output_str",
                ),
            )

        def result_output_path(result, filename: str) -> str | None:
            output_files = result.output_files or {}
            file_info = output_files.get(filename)
            if not isinstance(file_info, dict) or int(file_info.get("size") or 0) <= 0:
                return None
            if file_info.get("root_relative"):
                return filename
            return f"{result.plugin}/{filename}"

        def result_urls(plugin: str, filenames: tuple[str, ...]) -> list[str]:
            urls: list[str] = []
            for result in results:
                if result.plugin != plugin or result.status != ArchiveResult.StatusChoices.SUCCEEDED:
                    continue
                for filename in filenames:
                    output_path = result_output_path(result, filename)
                    if output_path:
                        urls.append(build_snapshot_url(str(obj.id), output_path, request=request, config=config))
            return urls

        screenshot_urls = result_urls("screenshot", ("screenshot.png",))
        extension_screenshot_urls = result_urls(EXTENSION_SCREENSHOT_PLUGIN, ("screenshot-1.png", "screenshot.png"))
        favicon_urls = result_urls("favicon", ("favicon.ico",))

        if not screenshot_urls and not extension_screenshot_urls and not favicon_urls:
            return None

        all_screenshot_urls = [*screenshot_urls, *extension_screenshot_urls]
        if all_screenshot_urls:
            img_url = all_screenshot_urls[0]
            fallbacks = [*all_screenshot_urls[1:], *favicon_urls]
            img_alt = "Screenshot"
            preview_class = "screenshot"
        else:
            img_url = favicon_urls[0]
            fallbacks = favicon_urls[1:]
            img_alt = "Favicon"
            preview_class = "favicon"

        fallback_list = ",".join(fallbacks)
        onerror_js = (
            "this.dataset.fallbacks && this.dataset.fallbacks.length ? "
            "(this.src=this.dataset.fallbacks.split(',').shift(), "
            "this.dataset.fallbacks=this.dataset.fallbacks.split(',').slice(1).join(',')) : "
            "this.remove()"
        )

        return {
            "img_url": img_url,
            "img_alt": img_alt,
            "preview_class": preview_class,
            "onerror_js": onerror_js,
            "fallback_list": fallback_list,
            "favicon_url": favicon_urls[0] if favicon_urls else "",
            "favicon_fallback_list": ",".join(favicon_urls[1:]),
        }

    @admin.display(description="", empty_value="")
    def url_favicon(self, obj):
        preview = self._get_preview_data(obj)
        if not preview:
            return ""

        favicon_url = preview.get("favicon_url") or ""
        if not favicon_url:
            return ""
        fallback_list = preview.get("favicon_fallback_list") or ""
        onerror_js = (
            "this.dataset.fallbacks && this.dataset.fallbacks.length ? "
            "(this.src=this.dataset.fallbacks.split(',').shift(), "
            "this.dataset.fallbacks=this.dataset.fallbacks.split(',').slice(1).join(',')) : "
            "this.closest('a') && this.closest('a').remove()"
        )

        return format_html(
            '<a href="{}" title="Open favicon" style="display:inline-flex; align-items:center; justify-content:center; width:32px; height:32px;">'
            '<img src="{}" alt="Favicon" decoding="async" loading="lazy" onerror="{}" data-fallbacks="{}" '
            'style="display:block; width:24px; height:24px; border-radius:6px; border:1px solid #e2e8f0; background:#fff; object-fit:contain; padding:2px;">'
            "</a>",
            favicon_url,
            favicon_url,
            onerror_js,
            fallback_list,
        )

    @admin.display(description="Preview", empty_value="")
    def preview_icon(self, obj):
        preview = self._get_preview_data(obj)
        if not preview:
            return None

        return format_html(
            '<img src="{}" alt="{}" class="snapshot-preview {}" decoding="async" loading="lazy" onerror="{}" data-fallbacks="{}">',
            preview["img_url"],
            preview["img_alt"],
            preview["preview_class"],
            preview["onerror_js"],
            preview["fallback_list"],
        )

    @admin.display(description=" ", empty_value="")
    def snapshot_summary(self, obj):
        request = self.request
        config = request.archivebox_config
        preview = self._get_preview_data(obj)
        stats = self._get_progress_stats(obj)
        archive_size = stats["output_size"] or 0
        size_txt = printable_filesize(archive_size) if archive_size else "pending"
        screenshot_html = ""

        if preview:
            screenshot_html = format_html(
                '<a href="{href}" title="Open snapshot live view" style="display:block; flex:0 0 220px; width:220px;">'
                '<img src="{src}" alt="{alt}" decoding="async" loading="lazy" onerror="{onerror}" data-fallbacks="{fallbacks}" '
                'style="display:block; width:100%; max-width:220px; aspect-ratio: 16 / 10; object-fit: cover; object-position: top; '
                'border-radius: 10px; border: 1px solid #e2e8f0; background: #f8fafc;">'
                "</a>",
                href=build_web_url(f"/{obj.archive_path}", request=request, config=config),
                src=preview["img_url"],
                alt=preview["img_alt"],
                onerror=preview["onerror_js"],
                fallbacks=preview["fallback_list"],
            )

        return format_html(
            '<div style="display:flex; gap:16px; align-items:flex-start;">'
            "{}"
            '<div style="min-width:0; flex:1;">'
            '<div style="font: 600 12px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">snap_dir size</div>'
            '<div style="font: 700 28px/1.1 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif; color:#0f172a; margin-bottom:8px;">{}</div>'
            '<div style="font-size:13px; line-height:1.5; color:#64748b;">'
            'Open <a href="{}"><code>{}</code></a> to inspect files.'
            "</div>"
            "</div>"
            "</div>",
            screenshot_html,
            size_txt,
            build_web_url(f"/{obj.archive_path}", request=request, config=config),
            obj.archive_path,
        )

    @admin.display(
        description="Files Saved",
        ordering="ar_succeeded_count",
    )
    def files(self, obj):
        results = self._get_prefetched_results(obj)
        if results is None:
            results = obj.archiveresult_set.only("plugin", "status", "output_size")

        plugins_with_output: dict[str, ArchiveResult] = {}
        for result in results:
            if result.status != ArchiveResult.StatusChoices.SUCCEEDED:
                continue
            if not result.output_size:
                continue
            plugins_with_output.setdefault(result.plugin, result)

        if not plugins_with_output:
            return mark_safe('<span style="opacity: 0.35;">...</span>')

        sorted_results = sorted(
            plugins_with_output.values(),
            key=lambda result: (_plugin_sort_order().get(result.plugin, 9999), result.plugin),
        )
        visible_results = sorted_results[:14]
        output = []
        request = self.request
        config = request.archivebox_config
        for result in visible_results:
            icon = mark_safe(get_plugin_icon(result.plugin))
            if not icon.strip():
                continue
            output.append(
                format_html(
                    '<a href="{}" class="exists-True" title="{}">{}</a>',
                    build_web_url(f"/{obj.archive_path_from_db}/{result.plugin}/", request=request, config=config),
                    result.plugin,
                    icon,
                ),
            )
        if len(sorted_results) > len(visible_results):
            output.append(
                format_html(
                    '<span title="{} more outputs">+{}</span>',
                    len(sorted_results) - len(visible_results),
                    len(sorted_results) - len(visible_results),
                ),
            )

        return format_html(
            '<span class="files-icons files-icons--compact" style="font-size: 1em; opacity: 0.8;">{}</span>',
            mark_safe("".join(output)),
        )

    @admin.display()
    def size(self, obj):
        request = self.request
        config = request.archivebox_config
        archive_size = self._get_progress_stats(obj)["output_size"] or 0
        if archive_size:
            size_txt = printable_filesize(archive_size)
            if archive_size > 52428800:
                size_txt = mark_safe(f"<b>{size_txt}</b>")
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')
        return format_html(
            '<a href="{}" title="View all files">{}</a>',
            build_web_url(f"/{obj.archive_path}", request=request, config=config),
            size_txt,
        )

    @admin.display(
        description="Status",
        ordering="status",
    )
    def status_with_progress(self, obj):
        """Show status with progress bar for in-progress snapshots."""
        stats = self._get_progress_stats(obj)

        # Status badge colors
        status_colors = {
            "queued": ("#f59e0b", "#fef3c7"),  # amber
            "started": ("#3b82f6", "#dbeafe"),  # blue
            "paused": ("#1d4ed8", "#dbeafe"),  # blue
            "sealed": ("#10b981", "#d1fae5"),  # green
            "succeeded": ("#10b981", "#d1fae5"),  # green
            "failed": ("#ef4444", "#fee2e2"),  # red
            "backoff": ("#f59e0b", "#fef3c7"),  # amber
            "skipped": ("#6b7280", "#f3f4f6"),  # gray
        }
        fg_color, bg_color = status_colors.get(obj.status, ("#6b7280", "#f3f4f6"))

        # For started snapshots, show progress bar
        if obj.status == "started" and stats["total"] > 0:
            percent = stats["percent"]
            running = stats["running"]
            succeeded = stats["succeeded"]
            failed = stats["failed"]

            return format_html(
                """<div style="min-width: 90px;">
                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                        <span class="snapshot-progress-spinner"></span>
                        <span style="font-size: 11px; color: #64748b;">{}/{} hooks</span>
                    </div>
                    <div style="background: #e2e8f0; border-radius: 4px; height: 6px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #10b981 0%, #10b981 {}%, #ef4444 {}%, #ef4444 {}%, #3b82f6 {}%, #3b82f6 100%);
                                    width: {}%; height: 100%; transition: width 0.3s;"></div>
                    </div>
                    <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">
                        ✓{} ✗{} ⏳{}
                    </div>
                </div>""",
                succeeded + failed + stats["skipped"],
                stats["total"],
                int(succeeded / stats["total"] * 100) if stats["total"] else 0,
                int(succeeded / stats["total"] * 100) if stats["total"] else 0,
                int((succeeded + failed) / stats["total"] * 100) if stats["total"] else 0,
                int((succeeded + failed) / stats["total"] * 100) if stats["total"] else 0,
                percent,
                succeeded,
                failed,
                running,
            )

        # For other statuses, show simple badge
        return format_html(
            '<span style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 500; background: {}; color: {};">{}</span>',
            bg_color,
            fg_color,
            obj.status.upper(),
        )

    @admin.display(
        description="Size",
        ordering="output_size",
    )
    def size_with_stats(self, obj):
        """Show archive size with output size from archive results."""
        stats = self._get_progress_stats(obj)
        output_size = stats["output_size"]
        size_bytes = output_size or 0

        if size_bytes:
            size_txt = printable_filesize(size_bytes)
            if size_bytes > 52428800:  # 50MB
                size_txt = mark_safe(f"<b>{size_txt}</b>")
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')

        # Show hook statistics
        if stats["total"] > 0:
            return format_html(
                '<a href="{}" title="View all files" style="white-space: nowrap;">'
                "{}</a>"
                '<div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">'
                "{}/{} hooks</div>",
                self.get_snapshot_files_url(obj),
                size_txt,
                stats["succeeded"],
                stats["total"],
            )

        return format_html(
            '<a href="{}" title="View all files">{}</a>',
            self.get_snapshot_files_url(obj),
            size_txt,
        )

    def _get_progress_stats(self, obj):
        cached_stats = obj.__dict__.get("_admin_progress_stats")
        if cached_stats is not None:
            return cached_stats

        results = self._get_prefetched_results(obj)
        if results is None:
            stats = obj.get_progress_stats()
            expected_total = self._get_expected_hook_total(obj)
            total = max(stats["total"], expected_total)
            completed = stats["succeeded"] + stats["failed"] + stats.get("skipped", 0) + stats.get("noresults", 0)
            stats["total"] = total
            stats["pending"] = max(total - completed - stats["running"], 0)
            stats["percent"] = int((completed / total * 100) if total > 0 else 0)
            obj._admin_progress_stats = stats
            return stats

        expected_total = self._get_expected_hook_total(obj)
        observed_total = len(results)
        total = max(observed_total, expected_total)
        succeeded = sum(1 for r in results if r.status == "succeeded")
        failed = sum(1 for r in results if r.status == "failed")
        running = sum(1 for r in results if r.status == "started")
        skipped = sum(1 for r in results if r.status == "skipped")
        noresults = sum(1 for r in results if r.status == "noresults")
        pending = max(total - succeeded - failed - running - skipped - noresults, 0)
        completed = succeeded + failed + skipped + noresults
        percent = int((completed / total * 100) if total > 0 else 0)
        is_sealed = obj.status not in (obj.StatusChoices.QUEUED, obj.StatusChoices.STARTED, obj.StatusChoices.PAUSED)
        stats = {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "running": running,
            "pending": pending,
            "skipped": skipped,
            "noresults": noresults,
            "percent": percent,
            "output_size": obj.output_size or 0,
            "is_sealed": is_sealed,
        }
        obj._admin_progress_stats = stats
        return stats

    def _get_prefetched_results(self, obj):
        if "_admin_output_results" in obj.__dict__:
            return obj.__dict__["_admin_output_results"]
        if "_admin_archiveresults" in obj.__dict__:
            return obj.__dict__["_admin_archiveresults"]
        if "archiveresult_set" in obj.__dict__.get("_prefetched_objects_cache", {}):
            return obj.archiveresult_set.all()
        return None

    def _get_expected_hook_total(self, obj) -> int:
        try:
            request = self.request
            if request.resolver_match.url_name in {"core_snapshot_changelist", "core_snapshot_change"}:
                return 0

            crawl = obj.crawl
            snapshot_config = obj.config or {}
            crawl_config = crawl.config or {}
            has_scoped_config = bool(snapshot_config or crawl_config)

            if request is not None and not has_scoped_config:
                cached_total = request.__dict__.get("archivebox_expected_snapshot_hook_total")
                if cached_total is None:
                    config = request.archivebox_config
                    cached_total = len(discover_hooks("Snapshot", config=config))
                    request.archivebox_expected_snapshot_hook_total = cached_total
                return cached_total

            if request is not None:
                scoped_cache = request.__dict__.get("archivebox_expected_snapshot_hook_totals_by_scope")
                if scoped_cache is None:
                    scoped_cache = {}
                    request.archivebox_expected_snapshot_hook_totals_by_scope = scoped_cache
                if snapshot_config:
                    cache_key = ("snapshot", json.dumps(snapshot_config, sort_keys=True, default=str))
                else:
                    cache_key = ("crawl", json.dumps(crawl_config, sort_keys=True, default=str))
                cached_total = scoped_cache.get(cache_key)
                if cached_total is None:
                    config = get_config(crawl=crawl, snapshot=obj if snapshot_config else None)
                    cached_total = len(discover_hooks("Snapshot", config=config))
                    scoped_cache[cache_key] = cached_total
                return cached_total

            return len(discover_hooks("Snapshot", config=get_config(crawl=crawl, snapshot=obj if snapshot_config else None)))
        except Exception:
            return 0

    def _get_prefetched_tags(self, obj):
        prefetched_cache = obj.__dict__.get("_prefetched_objects_cache", {})
        if "tags" in prefetched_cache:
            return list(prefetched_cache["tags"])
        return None

    def _get_ordering_fields(self, request):
        ordering = request.GET.get("o")
        if not ordering:
            return set()
        fields = set()
        for part in ordering.split("."):
            if not part:
                continue
            try:
                idx = abs(int(part)) - 1
            except ValueError:
                continue
            if 0 <= idx < len(self.list_display):
                fields.add(self.list_display[idx])
        return fields

    @admin.display(
        description="Original URL",
        ordering="url",
    )
    def url_str(self, obj):
        return format_html(
            '<a href="{}"><code style="user-select: all;">{}</code></a>',
            obj.url,
            obj.url[:128],
        )

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)

    def grid_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["snapshot_is_grid_view"] = True
        return self.changelist_view(request, extra_context=extra_context)

    @admin.action(
        description="🔁 Redo Failed",
    )
    def update_snapshots(self, request, queryset):
        queued = 0
        for snapshot in queryset:
            queued += snapshot.retry_failed_archiveresults()

        if queued:
            messages.success(
                request,
                f"Queued {queued} failed extractors for retry. The background runner will process them.",
            )
        else:
            messages.info(request, "No failed extractors were found in the selected snapshots.")

    @admin.action(
        description="🆕 Archive Now",
    )
    def resnapshot_snapshot(self, request, queryset):
        snapshots = list(queryset)
        if not snapshots:
            messages.info(request, "No snapshots selected.")
            return

        urls = "\n".join(snapshot.url for snapshot in snapshots if snapshot.url)
        if not urls:
            messages.info(request, "No valid snapshot URLs were found to archive.")
            return

        from archivebox.cli.archivebox_add import add

        # "Archive Now" is an explicit user re-archive — force ONLY_NEW=False
        # on the resulting crawl so existing snapshots don't cause the crawl to
        # seal immediately with zero new snapshots (the default ONLY_NEW=True
        # would skip any URLs that have ever been archived before).
        crawl, _ = add(urls=urls, bg=True, config={"ONLY_NEW": False})

        messages.success(
            request,
            f"Created 1 queued crawl with {len(snapshots)} URL(s). The background runner will create snapshots and process them.",
        )

        # Redirect to the new crawl's admin page so the user lands on the
        # work-in-progress crawl, not the old snapshot they re-archived from.
        # A snapshot-view redirect would race the runner — the new snapshot
        # may sit queued for a while before the runner creates the DB row.
        return redirect(f"/admin/crawls/crawl/{crawl.id}/change/#snapshots")

    @admin.action(
        description="🔄 Redo",
    )
    def overwrite_snapshots(self, request, queryset):
        queued = sum(snapshot.archive(overwrite=True) for snapshot in queryset)

        messages.success(
            request,
            f"Queued {queued} snapshots for full re-archive (overwriting existing). The background runner will process them.",
        )

    @admin.action(
        description="🗑️ Delete",
    )
    def delete_snapshots(self, request, queryset):
        """Delete snapshots in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list("pk", flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Snapshot.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(
            request,
            mark_safe(
                f"Successfully deleted {total} Snapshots ({deleted_count} total objects including related records). Don't forget to scrub URLs from import logs (data/sources) and error logs (data/logs) if needed.",
            ),
        )

    @admin.action(
        description="+",
    )
    def add_tags(self, request, queryset):
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get("tags", "")
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        tags = []
        for name in tag_names:
            tag, _ = get_or_create_tag(
                name,
                created_by=request.user if request.user.is_authenticated else None,
            )
            tags.append(tag)

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list("id", flat=True))
        num_snapshots = len(snapshot_ids)

        for tag in tags:
            SnapshotTag.objects.bulk_create(
                [SnapshotTag(snapshot_id=sid, tag_id=tag.pk) for sid in snapshot_ids],
                ignore_conflicts=True,
                batch_size=1000,
            )

        messages.success(
            request,
            f"Added {len(tags)} tag(s) to {num_snapshots} Snapshot(s).",
        )

    @admin.action(
        description="–",
    )
    def remove_tags(self, request, queryset):
        from archivebox.core.models import SnapshotTag

        # Get tags from the form - now comma-separated string
        tags_str = request.POST.get("tags", "")
        if not tags_str:
            messages.warning(request, "No tags specified.")
            return

        # Parse comma-separated tag names and find matching Tag objects (case-insensitive)
        tag_names = [name.strip() for name in tags_str.split(",") if name.strip()]
        tags = []
        for name in tag_names:
            tag = Tag.objects.filter(name__iexact=name).first()
            if tag:
                tags.append(tag)

        if not tags:
            messages.warning(request, "No matching tags found.")
            return

        # Get snapshot IDs efficiently (works with select_across for all pages)
        snapshot_ids = list(queryset.values_list("id", flat=True))
        num_snapshots = len(snapshot_ids)
        tag_ids = [t.pk for t in tags]

        deleted_count, _ = SnapshotTag.objects.filter(
            snapshot_id__in=snapshot_ids,
            tag_id__in=tag_ids,
        ).delete()

        messages.success(
            request,
            f"Removed {len(tags)} tag(s) from {num_snapshots} Snapshot(s) ({deleted_count} associations deleted).",
        )
