__package__ = "archivebox.core"

import json
import re
from copy import copy
from html import escape
from urllib.parse import urlsplit

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import path, reverse
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed, Http404
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.cache import patch_vary_headers
from django.utils.translation import gettext
from django.db.models import Count, Prefetch
from django import forms
from django.template import Context, Template, RequestContext
from django.template.loader import render_to_string
from django.contrib.admin.helpers import ActionForm
from django.contrib.admin.options import ActionLocation

from archivebox.config.common import get_config
from archivebox.misc.util import htmldecode, urldecode
from archivebox.misc.paginators import AcceleratedPaginator, snapshot_page
from archivebox.misc.logging_util import printable_filesize
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.search.admin import SearchResultsAdminMixin, SearchResultsChangeList, cached_search_rank_page
from archivebox.search.views import admin_snapshot_search_stream_view, search_row_cursor, streamed_page_ids
from archivebox.search.query import apply_snapshot_filters
from archivebox.core.routes_util import (
    build_snapshot_detail_path,
    build_snapshot_detail_url,
    build_snapshot_export_urls,
    build_snapshot_files_url,
    build_snapshot_role_output_url,
    build_snapshot_zip_url,
    get_snapshot_output_anchor,
)
from archivebox.core.tag_util import get_or_create_tag
from archivebox.core.templatetags.core_tags import snapshot_thumbnail, snapshot_url_text
from archivebox.plugins.hooks import discover_hooks
from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, get_plugin_catalog, get_plugin_icon, get_plugin_icon_asset
from archivebox.plugins.output_groups import (
    OUTPUT_GROUPS,
    display_plugin_name,
    output_group_for_plugin,
    order_output_plugins,
    plugin_icon_is_hidden,
    plugin_output_sizes,
)

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from archivebox.core.models import Tag, Snapshot, ArchiveResult, Folder
from archivebox.core.list_results_util import favicon_results, load_snapshot_list_results, snapshot_favicon_data
from archivebox.crawls.models import Crawl
from archivebox.core.admin_timing import timed_admin_view
from archivebox.core.admin_archiveresults import render_archiveresults_list
from archivebox.progressmonitor.views import progress_endpoint
from archivebox.core.permissions import (
    PERMISSIONS_CHOICES,
    PERMISSIONS_META,
    get_snapshot_permissions,
    normalize_permissions,
    render_permission_icon,
)
from archivebox.core.widgets import FolderPicker, TagEditorWidget, InlineTagEditorWidget


GLOBAL_CONTEXT = {}

SNAPSHOT_PERMISSION_META = PERMISSIONS_META


class SnapshotActionForm(ActionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define tags field in __init__ to avoid database access during app initialization
        self.fields["tags"] = forms.CharField(
            label="",
            required=False,
            widget=TagEditorWidget(attrs={"placeholder": "Edit tags...", "aria-label": "Edit tags"}),
        )
        self.fields["folder_destination"] = forms.ModelChoiceField(
            queryset=Folder.objects.destinations(),
            required=False,
            label="Folder",
            empty_label="No folder",
            widget=FolderPicker(destination=True),
        )

    def clean_tags(self):
        """Parse comma-separated tag names without touching the DB."""
        tags_str = self.cleaned_data.get("tags", "")
        if not tags_str:
            return []

        return [name.strip() for name in tags_str.split(",") if name.strip()]


class SnapshotDomainListFilter(admin.SimpleListFilter):
    title = "domain"
    parameter_name = "domain"

    def lookups(self, request, model_admin):
        return [(self.value(), self.value())] if self.value() else []

    def queryset(self, request, queryset):
        try:
            return apply_snapshot_filters(queryset, domain=self.value())
        except (ValueError, ValidationError):
            return queryset.none()


class SnapshotFolderListFilter(admin.SimpleListFilter):
    title = "folder"
    parameter_name = "folder"
    template = "admin/record_filter.html"
    picker_kind = "folder"

    def lookups(self, request, model_admin):
        if not self.value():
            return [("", "")]
        try:
            folders = Folder.objects.filter(pk=self.value()).only("name", "parent")
            return [(item["id"], item["name"]) for item in Folder.picker_choices(folders)] or [("", "")]
        except ValidationError:
            return [("", "")]

    def queryset(self, request, queryset):
        try:
            return apply_snapshot_filters(queryset, folder_id=self.value())
        except (ValueError, ValidationError):
            return queryset.none()


class TagNameListFilter(admin.SimpleListFilter):
    title = "By tag name"
    parameter_name = "tag"
    template = "admin/record_filter.html"
    picker_kind = "tag"

    def lookups(self, request, model_admin):
        selected = self.value()
        if selected and selected.isdigit():
            tag = Tag.objects.filter(pk=int(selected)).only("name").first()
            if tag:
                return [(selected, tag.name)]
        return [("", "")]

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
        return Snapshot._meta.get_field("status").choices

    def queryset(self, request, queryset):
        value = self.value()
        return apply_snapshot_filters(queryset, status=value if value in dict(Snapshot._meta.get_field("status").choices) else None)


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
        return apply_snapshot_filters(queryset, archive_state=self.value())


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
        return apply_snapshot_filters(queryset, size=self.value())


class SnapshotResultHealthListFilter(admin.SimpleListFilter):
    title = "ArchiveResult status"
    parameter_name = "archiveresult_status"

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
        return apply_snapshot_filters(queryset, archiveresult_status=self.value())


class SnapshotChangeList(SearchResultsChangeList):
    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params)
        lookup_params.pop("sidebar", None)
        lookup_params.pop("site_scope", None)
        lookup_params.pop("domain_search", None)
        return lookup_params

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        resolver_name = request.resolver_match.url_name
        self.embedded_changelist = request.GET.get("_embedded") == "crawl"
        self.snapshot_is_grid_view = not self.embedded_changelist and (
            resolver_name == "grid" or request.path.rstrip("/").endswith("/grid")
        )

    def _attach_archiveresult_summaries(self, snapshots):
        if not snapshots:
            return

        # Progress counts, file icons, favicons and thumbnails come from plain
        # rows plus the few manifest entries their links need: responses/wget
        # manifests hold thousands of entries (see list_results_util).
        list_results = load_snapshot_list_results(snapshots, images_only=True)
        for obj in snapshots:
            summary = list_results[obj.pk]
            counts = summary.status_counts + summary.unnamed_status_counts
            total = sum(counts.values())
            succeeded = counts[ArchiveResult.StatusChoices.SUCCEEDED]
            failed = counts[ArchiveResult.StatusChoices.FAILED]
            running = counts[ArchiveResult.StatusChoices.STARTED]
            skipped = counts[ArchiveResult.StatusChoices.SKIPPED]
            noresults = counts[ArchiveResult.StatusChoices.NORESULTS]
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
            # files() selects successful links itself, but needs every sibling
            # hook to count shared plugin files once and order the icons.
            obj.__dict__["_admin_output_results"] = summary.results
            obj.__dict__["_snapshot_card_results"] = summary.results
            obj.__dict__["_snapshot_thumbnail_image_paths"] = summary.thumbnail_image_paths

    def get_results(self, request):
        if getattr(request, "_archivebox_search_filter_only", False):
            return
        from archivebox.progressmonitor.collection import snapshot_list_count

        # An expired/in-flight search cannot validate a later page yet. Keep
        # its URL intact while showing provisional rows until the stream settles.
        pending = self.query and request.GET.get("_embedded") != "crawl" and not getattr(request, "_archivebox_search_complete", False)
        if pending and not getattr(request, "_archivebox_search_ranks", None):
            self.page_num = 1
        start = (self.page_num - 1) * self.list_per_page
        size = self.list_max_show_all if self.show_all else self.list_per_page
        queryset_ids = self.queryset.values_list("pk", flat=True)
        root_ids = self.root_queryset.values_list("pk", flat=True)
        streamed_ids = streamed_page_ids(request)
        indexed_count = None
        if (
            streamed_ids is None
            and request.GET.get("domain")
            and (not self.query or getattr(request, "_archivebox_search_complete", False))
        ):
            # Reuse the exact indexed count to choose the smaller paging scope.
            indexed_count = self.queryset.order_by().values("pk").count()
        elif streamed_ids is None and not self.root_queryset.query.where and not self.queryset.query.is_empty():
            scope = {key for key, value in request.GET.items() if value and key not in {"p", "sidebar"}}
            single_related_tag = scope == {"tags__id__exact"} and len(request.GET.getlist("tags__id__exact")) == 1
            if scope == {"tag"} or single_related_tag:
                from archivebox.core.tag_util import annotate_tag_snapshot_counts

                tag_id = request.GET.get("tag") or request.GET["tags__id__exact"]
                # The unique membership rows give the exact total through the
                # existing tag index, without visiting every Snapshot row.
                indexed_count = (
                    annotate_tag_snapshot_counts(Tag.objects.filter(pk=tag_id)).values_list("num_snapshots", flat=True).first() or 0
                )
                if single_related_tag:
                    # Django adds DISTINCT to generic related-field lookups.
                    # The single tag's unique links already produce one ID per snapshot.
                    queryset_ids = root_ids.filter(tags__id=tag_id).order_by(*queryset_ids.query.order_by)
            elif scope == {"folder"}:
                folder_id = request.GET["folder"]
                folder = Folder.objects.filter(pk=folder_id).only("rules").first() if folder_id != "unfiled" else None
                if folder_id == "unfiled" or (folder is not None and not folder.is_smart):
                    # Regular-folder membership is covered by the folder index.
                    # Smart folders and combined filters retain async counts.
                    indexed_count = self.queryset.order_by().values("folder_id").count()

        def read_page(offset, limit):
            if streamed_ids is not None:
                return streamed_ids[offset : offset + limit]
            cached_page = cached_search_rank_page(request, start=offset, size=limit)
            if cached_page is not None:
                return cached_page
            return snapshot_page(queryset_ids, base_queryset=root_ids, start=offset, size=limit, count=indexed_count)

        preview = bool(self.query and not self.show_all and not start and request.headers.get("X-ArchiveBox-Search-Fragment") == "preview")
        page_ids = read_page(0 if self.show_all else start, 2 if preview else size + 1)
        if pending and start and not page_ids:
            # A bookmark can request a page beyond the confirmed matches. Keep
            # displaying the first page until this stream reaches that offset.
            self.page_num = 1
            start = 0
            page_ids = read_page(0, size + 1)
        self.preview_has_more = preview and len(page_ids) > 1
        if self.show_all and len(page_ids) > size:
            self.show_all = False
            size = self.list_per_page
            page_ids = read_page(start, size + 1) if start else page_ids[: size + 1]
        elif self.show_all:
            start = 0
            self.page_num = 1
        if not page_ids and start:
            from django.contrib.admin.options import IncorrectLookupParameters

            raise IncorrectLookupParameters
        observed = start + len(page_ids)
        self.result_count_exact = not self.preview_has_more and len(page_ids) <= size
        count = observed
        if indexed_count is not None:
            count = indexed_count
            self.result_count_exact = True
        # Other queries retain the lookahead lower bound for next/previous links.
        self.queryset.query._archivebox_count_hint = count
        super().get_results(request)
        # Keep wide snapshot columns and related rows out of the full sort and
        # OFFSET scan, as on the public index. Preserve the selected order while
        # loading only displayed rows, not the lookahead or discarded probes.
        # Cached-search page IDs were already intersected with the changelist
        # scope. Recheck that scope on fetch, without binding every cached ID
        # again just to read the displayed rows.
        rank_scope = getattr(request, "_archivebox_search_rank_scope", self.queryset)
        page_ids = page_ids[:1] if preview else page_ids
        rows = {obj.pk: obj for obj in rank_scope.filter(pk__in=page_ids[:size]).order_by()}
        self.result_list = [rows[pk] for pk in page_ids[:size] if pk in rows]
        # Rank is a presentation attribute only on displayed rows. Keep the
        # database expression as an ordering alias, not a repeated SELECT.
        search_ranks = getattr(request, "_archivebox_search_ranks", None)
        if search_ranks is not None:
            for obj in self.result_list:
                obj.search_rank = search_ranks[obj.pk.hex]
        summary = None
        estimate = None
        if not self.result_count_exact and not self.queryset.query.where:
            from archivebox.misc.db import approximate_row_counts
            from archivebox.progressmonitor.collection import collection_summary
            from django.db import connections

            # A cold exact count reads the whole index even when a display
            # total is already available. Avoid competing with page reads.
            collection = collection_summary(request.user, refresh=False) if request.user.is_superuser else None
            if collection:
                summary = {"count": collection["snapshots"]}
            else:
                estimate = approximate_row_counts(connections[self.queryset.db]).get(Snapshot._meta.db_table)
        if summary is None and not self.result_count_exact:
            # Reuse an earlier exact sample ahead of a planner estimate.
            # Filtered and unanalyzed lists still refresh in the background.
            summary = snapshot_list_count(self.queryset, refresh=estimate is None)
            if summary is None and estimate is not None:
                summary = {"count": estimate}
        self.display_result_count = max(observed, summary["count"]) if summary else count
        self.result_count_cached = summary is not None
        if self.result_count_exact or self.result_count_cached:
            display_paginator = AcceleratedPaginator(range(self.display_result_count), self.list_per_page)
            self.display_num_pages = display_paginator.num_pages
            page_links = {}
            for width, neighbors in (("compact", 1), ("medium", 4), ("wide", 8)):
                # Merge Django's ranges so each page link is rendered once.
                # The left and right ellipses occupy separate positions.
                before_current = True
                for number in display_paginator.get_elided_page_range(self.page_num, on_each_side=neighbors, on_ends=1):
                    if isinstance(number, int):
                        position = (number, 0)
                        before_current = before_current and number != self.page_num
                    else:
                        position = (1, 1) if before_current else (self.display_num_pages, -1)
                    page_links.setdefault(position, {"number": number, "widths": []})["widths"].append(width)
            self.display_page_links = [link for _, link in sorted(page_links.items())]
            for link in self.display_page_links:
                number = link["number"]
                link["url"] = self.get_query_string({"p": number}, remove=["all"]) if isinstance(number, int) else None
        self.next_page_url = self.get_query_string({"p": self.page_num + 1}, remove=["all"]) if len(page_ids) > size else None
        self.previous_page_url = self.get_query_string({"p": self.page_num - 1}, remove=["all"]) if self.page_num > 1 else None
        previous = request.headers.get("X-ArchiveBox-Search-Rows")
        self.retained_rows = 0
        if previous and self.query and request.method == "GET" and request.GET.get("_embedded") != "crawl":
            self.retained_rows, self.row_cursor = search_row_cursor(self.result_list, previous)
        self._attach_archiveresult_summaries(self.result_list[self.retained_rows :])


class SnapshotAdminForm(forms.ModelForm):
    """Custom form for Snapshot admin with tag editor widget."""

    url = forms.CharField(widget=forms.TextInput)
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
    change_list_template = "admin/core/snapshot/change_list.html"
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
        "created_at_display",
        "preview_icon",
        "title_str",
        "tags_inline",
        "status_with_progress",
        "files",
        "size_with_stats",
    )
    list_display_links = ("created_at_display",)
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
        SnapshotDomainListFilter,
        SnapshotFolderListFilter,
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
                "fields": ("crawl", "folder"),
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
        "move_to_folder",
        "add_tags",
        "remove_tags",
        "resnapshot_snapshot",
        "update_snapshots",
        "overwrite_snapshots",
        "set_snapshot_permissions",
        "delete_selected",
        "delete_snapshots",
    ]
    inlines = []  # Removed TagInline, using TagEditorWidget instead

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "folder":
            kwargs["widget"] = FolderPicker(destination=True)
            kwargs["queryset"] = Folder.objects.destinations()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    list_per_page = 50

    def action_checkbox(self, obj):
        # Django's fixed action widget needs no per-row template/context build.
        # Keep its field name, attributes, translated label and escaping intact.
        return format_html(
            '<input type="checkbox" name="{}" value="{}" class="action-select" aria-label="{}">',
            admin.helpers.ACTION_CHECKBOX_NAME,
            str(obj.pk),
            gettext("Select this object for an action - {}").format(str(obj)),
        )

    @admin.display(description="Date", ordering="created_at")
    def created_at_display(self, obj):
        created_at = timezone.localtime(obj.created_at)
        now = timezone.now()
        minutes_ago = max(0, int((now - obj.created_at).total_seconds() // 60))
        relative_time = "just now" if minutes_ago == 0 else f"{minutes_ago}m ago" if minutes_ago < 60 else f"{minutes_ago // 60}hr ago"
        date = date_format(created_at, "Y-m-d")
        time = date_format(created_at, "g:i A")
        return format_html(
            '<span class="snapshot-created-at{}"><span class="snapshot-created-at__date">{}</span><span class="snapshot-created-at__time">{}</span>'
            '<span class="snapshot-created-at__relative" title="{}">{}</span></span>',
            " snapshot-created-at--today" if created_at.date() == timezone.localdate(now) else "",
            date,
            time,
            f"{date} {time} {date_format(created_at, 'T')}",
            relative_time,
        )

    action_form = SnapshotActionForm
    paginator = AcceleratedPaginator

    save_on_top = True
    show_full_result_count = False

    def get_changelist(self, request, **kwargs):
        return SnapshotChangeList

    def get_ordering(self, request):
        if request.GET.get("o"):
            return []
        if folder_id := request.GET.get("folder"):
            from archivebox.core.smart_folders import RuleQuery

            try:
                folder = Folder.objects.filter(pk=folder_id).first()
            except (ValueError, ValidationError):
                folder = None
            if folder and folder.is_smart:
                return RuleQuery.ordering(folder)
        return super().get_ordering(request)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        self = copy(self)
        self.request = request
        return super().changeform_view(request, object_id, form_url, extra_context)

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

    def render_embedded_changelist(self, request, scoped_params):
        snapshot_changelist = reverse("admin:core_snapshot_changelist")
        params = request.GET.copy()
        for key, value in scoped_params.items():
            params[key] = value
        params.pop("_embedded", None)
        full_url = f"{snapshot_changelist}?{params.urlencode()}"
        changelist_request = copy(request)
        changelist_request.method = "GET"
        changelist_request.path = snapshot_changelist
        changelist_request.GET = params.copy()
        changelist_request.GET.update({"_embedded": "crawl", "per_page": params.get("per_page", "200")})
        changelist_request.POST = request.POST.copy()
        changelist_request.POST.clear()
        response = self.changelist_view(changelist_request, extra_context={"embedded_changelist": True})
        return mark_safe(
            render_to_string(
                "admin/core/snapshot/embedded_changelist.html",
                {
                    **response.context_data,
                    "snapshot_changelist_url": full_url,
                    "changelist_form_action": f"{snapshot_changelist}?{changelist_request.GET.urlencode()}",
                },
                request=request,
            ),
        )

    @timed_admin_view
    def changelist_view(self, request, extra_context=None):
        # Django shares ModelAdmin instances; deferred rendering must keep its own request.
        self = copy(self)
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
        search_fragment = bool(
            request.method == "GET"
            and not embedded_changelist
            and request.GET.get("q")
            and request.headers.get("X-ArchiveBox-Search-Rows"),
        )
        # Streamed results replace only #content-main. The live sidebar retains
        # its expanded folders, pagination and export menus across submissions.
        if not search_fragment:
            from archivebox.core.sidebar import sidebar_context

            extra_context["folder_tree"] = Folder.tree()
            if not embedded_changelist:
                extra_context.update(sidebar_context(request, folder_tree=extra_context["folder_tree"]))
            extra_context["selected_folder"] = request.GET.get("folder", "")
            selected = next((folder for folder in extra_context["folder_tree"] if str(folder.pk) == extra_context["selected_folder"]), None)
            folders_by_id = {folder.pk: folder for folder in extra_context["folder_tree"]}
            breadcrumbs = []
            while selected:
                breadcrumbs.append(selected)
                selected = folders_by_id.get(selected.parent_id)
            extra_context["folder_breadcrumbs"] = list(reversed(breadcrumbs))
        extra_context["search_fragment"] = search_fragment
        if search_fragment:
            # Render the inherited changelist content (including custom
            # object-tools blocks) without the enclosing admin document.
            extra_context["changelist_base_template"] = "admin/core/snapshot/search_fragment.html"
        extra_context["list_export_urls"] = build_snapshot_export_urls(request.GET, request=request)
        try:
            try:
                response = super().changelist_view(request, extra_context | GLOBAL_CONTEXT)
                patch_vary_headers(
                    response,
                    (
                        "X-ArchiveBox-Search-Rows",
                        "X-ArchiveBox-Search-Generation",
                        "X-ArchiveBox-Search-Page",
                        "X-ArchiveBox-Search-Fragment",
                    ),
                )
                cl = (getattr(response, "context_data", None) or {}).get("cl")
                if cl and getattr(cl, "preview_has_more", False):
                    response["X-ArchiveBox-Search-More-Rows"] = "1"
                if cl and hasattr(cl, "row_cursor"):
                    response["X-ArchiveBox-Search-Rows"] = cl.row_cursor
                    if cl.retained_rows:
                        # Actions and pagination use the entire page. Only the
                        # table/grid renderer receives the newly arrived suffix.
                        additions = copy(cl)
                        additions.result_list = cl.result_list[cl.retained_rows :]
                        response.context_data["additions"] = additions
                        response.template_name = "admin/core/snapshot/search_rows.html"
                        response["X-ArchiveBox-Search-Retained"] = str(cl.retained_rows)
                return response
            except Exception as e:
                self.message_user(request, f"Error occurred while loading the page: {str(e)} {request.GET} {request.POST}")
                return super().changelist_view(request, GLOBAL_CONTEXT)
        finally:
            self.list_per_page = saved_list_per_page

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        actions = super().get_actions(request, action_location=action_location)
        if not actions:
            return {}
        # Keep the old action endpoint for callers, while the UI uses Django's
        # normal confirmation before queueing native filesystem deletion.
        if request.POST.get("action") != "delete_snapshots":
            actions.pop("delete_snapshots", None)
        return actions

    def lookup_allowed(self, lookup, value, request=None):
        if lookup in {"crawl__id__exact", "crawl_id__exact", "crawl_id"}:
            return True
        return super().lookup_allowed(lookup, value, request=request)

    def get_snapshot_view_url(self, obj: Snapshot) -> str:
        return build_snapshot_detail_url(obj.archive_path_from_db, request=self.request)

    def get_snapshot_files_url(self, obj: Snapshot) -> str:
        request = self.request
        return build_snapshot_files_url(str(obj.id), request=request, config=request.archivebox_config)

    def get_snapshot_zip_url(self, obj: Snapshot) -> str:
        request = self.request
        return build_snapshot_zip_url(str(obj.id), request=request, config=request.archivebox_config)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("export.<str:format>", self.export_view, name="core_snapshot_export"),
            path("export-jobs/<str:process_id>/", self.export_job_view, name="core_snapshot_export_job"),
            path(
                "export-jobs/<str:process_id>/download/",
                self.export_job_view,
                {"action": "download"},
                name="core_snapshot_export_download",
            ),
            path("export-jobs/<str:process_id>/cancel/", self.export_job_view, {"action": "cancel"}, name="core_snapshot_export_cancel"),
            path("grid/", self.admin_site.admin_view(self.grid_view), name="grid"),
            path("search-stream/", self.admin_site.admin_view(self.search_stream_view), name="core_snapshot_search_stream"),
            path(
                "<path:object_id>/preview/<str:plugin>/<path:filename>",
                self.admin_site.admin_view(self.preview_view, cacheable=True),
                name="core_snapshot_preview",
            ),
            path("<path:object_id>/redo-failed/", self.admin_site.admin_view(self.redo_failed_view), name="core_snapshot_redo_failed"),
            path(
                "<path:object_id>/set-permissions/",
                self.admin_site.admin_view(self.set_permissions_view),
                name="core_snapshot_set_permissions",
            ),
        ]
        return custom_urls + urls

    def export_view(self, request, format="rss"):
        from archivebox.core.exports import snapshot_export_view

        return snapshot_export_view(request, format=format)

    def export_job_view(self, request, process_id, action="status"):
        from archivebox.core.exports import snapshot_export_job_view

        return snapshot_export_job_view(request, process_id, action=action)

    @admin.action(description="Move to folder", permissions=["change"])
    def move_to_folder(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied
        folder_id = request.POST.get("folder_destination")
        folder = get_object_or_404(Folder, pk=folder_id) if folder_id else None
        count = Folder.move_snapshots(queryset, folder.pk if folder else None)
        self.message_user(request, f"Moved {count} snapshot(s) to {folder.name if folder else 'No folder'}.")

    def preview_view(self, request, object_id, plugin, filename):
        """Serve a saved image output from the authenticated admin origin."""
        snapshot = get_object_or_404(Snapshot, pk=object_id)
        if not self.has_view_or_change_permission(request, snapshot):
            raise PermissionDenied
        results = (
            snapshot.archiveresult_set.filter(plugin=plugin, status=ArchiveResult.StatusChoices.SUCCEEDED)
            .only("plugin", "output_files", "output_str")
            .order_by("id")
        )
        output_path = None
        for result in results:
            try:
                manifest = result.output_file_map()
                output_path = result.output_file_path(filename, output_file_map=manifest)
                if not manifest:
                    # Legacy captures can have a saved image path and no manifest.
                    primary = result.embed_path_db(manifest)
                    if primary and primary.removeprefix(f"{plugin}/") == filename:
                        output_path = primary
            except (TypeError, ValueError, OverflowError):
                continue
            if output_path:
                break
        if not output_path:
            raise Http404("Snapshot image does not exist")
        request.archivebox_cache_policy = "private"
        response = serve_static_with_byterange_support(request, output_path, document_root=snapshot.output_dir)
        if response.status_code != 304 and not response.headers.get("Content-Type", "").lower().startswith("image/"):
            raise Http404("Snapshot preview is not an image")
        response.headers["Vary"] = "Cookie"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
        if is_change_view:
            prefetches = [
                "tags",
                Prefetch(
                    "archiveresult_set",
                    queryset=ArchiveResult.objects.only(
                        "id",
                        "snapshot_id",
                        "modified_at",
                        "plugin",
                        "status",
                        "output_size",
                        "output_str",
                        "output_files",
                    ),
                ),
            ]
        else:
            prefetches = [
                # The table and grid only display tag IDs and names, so fetching
                # ownership and converting timestamps would add work per pill.
                Prefetch("tags", queryset=Tag.objects.only("id", "name")),
                Prefetch(
                    "crawl",
                    queryset=Crawl.objects.select_related("created_by").only(
                        "id",
                        "created_by_id",
                        "created_by__id",
                        "created_by__username",
                    ),
                ),
            ]

        qs = super().get_queryset(request)
        try:
            qs = apply_snapshot_filters(
                qs,
                site_scopes=request.GET.getlist("site_scope"),
                domain_search=request.GET.get("domain_search"),
            )
        except ValueError:
            qs = qs.none()
        if is_change_view:
            qs = qs.select_related("crawl__created_by").defer("notes")
        else:
            qs = qs.only(
                "id",
                "created_at",
                "modified_at",
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

    def snapshot_permissions_choices(self):
        return [(value, label, SNAPSHOT_PERMISSION_META[value][0]) for value, label in PERMISSIONS_CHOICES]

    @admin.display(
        description=format_html('<span title="Visibility" aria-label="Visibility">{}</span>', render_permission_icon("private")),
        ordering="permissions",
    )
    def permissions_badge(self, obj):
        permissions = obj.__dict__.get("snapshot_permissions")
        if permissions is None:
            permissions = obj.permissions
        permissions = normalize_permissions(permissions)
        icon, label, _, _ = SNAPSHOT_PERMISSION_META[permissions]
        return format_html(
            '<span class="snapshot-permissions-quick" data-current-permissions="{}" data-permissions-url="{}">'
            '<button type="button" class="snapshot-permissions-button snapshot-permissions-{}" title="{}" aria-label="Change snapshot permissions: {}" aria-haspopup="menu" aria-expanded="false">'
            '<span class="snapshot-permissions-icon" aria-hidden="true">{}</span>'
            "</button></span>",
            permissions,
            reverse(f"{self.admin_site.name}:core_snapshot_set_permissions", args=[obj.pk]),
            permissions,
            label,
            label,
            icon,
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
        favicon_url = build_snapshot_role_output_url(
            obj,
            "list_icon",
            request=request,
            config=config,
            fallback_to_default=True,
        )
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
        title_raw = (obj.title or "").strip()
        url_raw = (obj.url or "").strip()
        title_normalized = title_raw.lower()
        url_normalized = url_raw.lower()
        show_title = bool(title_raw) and title_normalized != "pending..." and title_normalized != url_normalized
        css_class = "fetched" if show_title else "pending"

        detail_url = self.get_snapshot_view_url(obj)
        title_html = ""
        if show_title:
            title_html = format_html(
                '<a href="{}" title="{}"><b class="status-{}">{}</b></a>',
                detail_url,
                urldecode(htmldecode(title_raw)),
                css_class,
                urldecode(htmldecode(title_raw)),
            )

        else:
            # Untitled documents still need a readable primary link in compact rows.
            # Keep the full URL below it for disambiguation, without inventing a title.
            try:
                parsed_url = urlsplit(url_raw)
                fallback = urldecode(parsed_url.path.rstrip("/").rsplit("/", 1)[-1]) or parsed_url.hostname or url_raw
            except ValueError:
                # Legacy rows can contain malformed netlocs; rendering must not 500.
                fallback = url_raw
            title_html = format_html(
                '<a class="snapshot-title-fallback" href="{}" title="{}"><b>{}</b></a>',
                detail_url,
                url_raw,
                fallback,
            )

        favicon = self._get_favicon_data(obj) or {}
        favicon_html = (
            format_html(
                '<img class="snapshot-url-favicon" src="{}" alt="" loading="lazy" decoding="async" onerror="this.hidden=true">',
                favicon["url"],
            )
            if favicon.get("url")
            else ""
        )
        return format_html(
            '<a class="snapshot-title-detail-hitbox" href="{}" aria-label="Open snapshot details"></a>'
            "{}"
            '<div class="snapshot-title-url">'
            '<a class="snapshot-original-url" href="{}">{}<code style="user-select: all;">{}</code></a>'
            "</div>",
            detail_url,
            title_html,
            (url_raw or obj.url) if show_title else detail_url,
            favicon_html,
            snapshot_url_text(url_raw or obj.url),
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
        permissions = normalize_permissions(obj.__dict__.get("snapshot_permissions", obj.permissions))
        _, permission_label, _, _ = SNAPSHOT_PERMISSION_META[permissions]
        permission_svg = render_permission_icon(permissions)
        return format_html(
            '<span class="snapshot-row-permission" role="img" title="{}" aria-label="{}">{}</span>'
            '<span class="tags-inline-editor tags-inline-editor--compact">{}</span>',
            permission_label,
            permission_label,
            permission_svg,
            tags_html,
        )

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

    def _get_favicon_data(self, obj):
        results = self._get_prefetched_results(obj)
        if results is None:
            results = favicon_results().filter(snapshot_id=obj.pk)
        return snapshot_favicon_data(obj.pk, results, request=self.request)

    def _render_thumbnail(self, obj, width="100px", height="100px"):
        return snapshot_thumbnail(
            Context({"request": self.request, "CONFIG": self.request.archivebox_config}),
            obj,
            admin=True,
            width=width,
            height=height,
        )

    @admin.display(description="", empty_value="")
    def url_favicon(self, obj):
        favicon = self._get_favicon_data(obj)
        if not favicon:
            return ""

        favicon_url = favicon.get("url") or ""
        if not favicon_url:
            return ""
        fallback_list = favicon.get("fallbacks") or ""
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
        return format_html(
            '<a href="{}" title="Open snapshot details">{}</a>',
            self.get_snapshot_view_url(obj),
            self._render_thumbnail(obj, height="38px"),
        )

    @admin.display(description=" ", empty_value="")
    def snapshot_summary(self, obj):
        stats = self._get_progress_stats(obj)
        archive_size = stats["output_size"] or 0
        size_txt = printable_filesize(archive_size) if archive_size else "pending"
        screenshot_html = format_html(
            '<a href="{}" title="Open snapshot live view" style="display:block;flex:0 0 220px;">{}</a>',
            self.get_snapshot_view_url(obj),
            self._render_thumbnail(obj, width="220px", height="138px"),
        )

        return format_html(
            '<div style="display:flex; gap:16px; align-items:flex-start;">'
            "{}"
            '<div style="min-width:0; flex:1;">'
            '<div style="font: 600 12px/1.4 var(--font-family-primary); color:#64748b; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">snap_dir size</div>'
            '<div style="font: 700 28px/1.1 var(--font-family-primary); color:#0f172a; margin-bottom:8px;">{}</div>'
            '<div style="font-size:13px; line-height:1.5; color:#64748b;">'
            'Open <a href="{}"><code>{}</code></a> to inspect files.'
            "</div>"
            "</div>"
            "</div>",
            screenshot_html,
            size_txt,
            self.get_snapshot_files_url(obj),
            obj.archive_path_from_db,
        )

    @admin.display(
        description="Files Saved",
        ordering="ar_succeeded_count",
        empty_value="",
    )
    def files(self, obj):
        from archivebox.plugins.discovery import get_plugin_name

        results = self._get_prefetched_results(obj)
        if results is None:
            results = load_snapshot_list_results([obj])[obj.pk].results

        plugins_with_output: dict[str, ArchiveResult] = {}
        for result in results:
            if result.status != ArchiveResult.StatusChoices.SUCCEEDED:
                continue
            if not result.output_size:
                continue
            plugins_with_output.setdefault(result.plugin, result)

        if not plugins_with_output:
            return ""

        output_sizes = plugin_output_sizes(result for result in results if result.plugin in plugins_with_output)
        sorted_results = [plugins_with_output[plugin] for plugin in order_output_plugins(plugins_with_output, output_sizes)]
        icons_by_group: dict[str, list[str | tuple[str, str]]] = {group_id: [] for group_id, _ in OUTPUT_GROUPS}
        request = self.request
        detail_url = escape(self.get_snapshot_view_url(obj))
        icon_metadata = request.__dict__.setdefault("_archivebox_file_icon_metadata", {})
        defined_plugins = request.__dict__.setdefault("_archivebox_file_icon_templates", set())
        definitions = []
        for result in sorted_results:
            plugin = result.plugin
            if plugin not in icon_metadata:
                icon = str(get_plugin_icon(plugin))
                if not plugin_icon_is_hidden(plugin) and icon.strip():
                    cover = icon
                    if asset := get_plugin_icon_asset(plugin):
                        url = reverse("plugin-icon", kwargs={"plugin": plugin, "fingerprint": asset[0]})
                        image = f'src="{escape(url)}" width="16" height="16" alt=""'
                        svg_start = icon.index("<svg")
                        wrapper = icon[icon.index("<span ") : svg_start]
                        icon = f"{icon[:svg_start]}<img {image}>{icon[icon.rindex('</svg>') + 6 :]}"
                        cover = icon
                        # Only the packaged badge has the same look on an img.
                        # The popup template keeps the full wrapper and artwork credits.
                        badge = f"abx-output-icon abx-output-icon--{plugin}"
                        if get_plugin_catalog()[plugin].path.parent == BUILTIN_PLUGINS_DIR and re.fullmatch(
                            rf'<span class="{badge}" title="[^"]*"(?: role="img" aria-label="[^"]*")?>',
                            wrapper,
                        ):
                            cover = f'<img class="{badge}" {image}>'
                    fragment = build_snapshot_detail_path("", output_path=get_plugin_name(plugin), prefix="")
                    icon_metadata[plugin] = (output_group_for_plugin(plugin), escape(display_plugin_name(plugin)), icon, cover, fragment)
                else:
                    icon_metadata[plugin] = None
            metadata = icon_metadata[plugin]
            if metadata is None:
                continue
            group, label, icon, _, fragment = metadata
            if isinstance(result, ArchiveResult):
                output_path = result.embed_path()
                anchor_path = get_snapshot_output_anchor(plugin, output_path) if output_path else None
                if not anchor_path:
                    continue
                target_fragment = build_snapshot_detail_path("", output_path=anchor_path, prefix="")
            elif result.icon_anchor():
                target_fragment = fragment
            else:
                continue

            # List results link to the same plugin card on each snapshot. Keep
            # only alternate file fragments in the row and share the usual link
            # with the existing artwork template.
            icons_by_group[group].append(plugin if target_fragment == fragment else (plugin, target_fragment))
            if plugin not in defined_plugins:
                # Template contents remain inert. Off-cover image requests and
                # popup DOM are both deferred until a pile is opened.
                definitions.append(
                    f'<template id="abx-file-icon-{escape(plugin)}" data-label="{label}" data-fragment="{escape(fragment)}">{icon}</template>',
                )
                defined_plugins.add(plugin)

        output = []
        for group_id, label in OUTPUT_GROUPS:
            icons = icons_by_group[group_id]
            if not icons:
                continue
            column = len(output)
            label = escape(label)
            pile_style = f' style="--files-icon-popup-left:{column * -22}px"' if column else ""
            top_plugin = icons[0] if isinstance(icons[0], str) else icons[0][0]
            cover = icon_metadata[top_plugin][3]
            # JSON strings use double quotes. A single-quoted attribute avoids
            # escaping those quotes while still protecting plugin names.
            members = escape(json.dumps(icons, ensure_ascii=False, separators=(",", ":")), quote=False).replace("'", "&#x27;")
            output.append(
                f'<span class="files-icon-pile files-icon-pile--{escape(group_id)}" role="group" aria-label="{label} saved outputs" '
                f"data-files-icons='{members}'{pile_style}>"
                f'<a href="{detail_url}" class="files-icon-pile-top files-icon-pile-cover files-icon-plugin--{escape(top_plugin)}" '
                f'aria-label="{label}" data-tooltip="{label}">{cover}</a></span>',
            )

        return mark_safe(
            f'{"".join(definitions)}<span class="files-icons files-icons--compact" style="font-size: 1em;">{"".join(output)}</span>',
        )

    @admin.display(empty_value="")
    def size(self, obj):
        archive_size = self._get_progress_stats(obj)["output_size"] or 0
        if archive_size:
            size_txt = printable_filesize(archive_size)
            if archive_size > 52428800:
                size_txt = mark_safe(f"<b>{size_txt}</b>")
        else:
            return ""
        return format_html(
            '<a href="{}" title="View all files">{}</a>',
            self.get_snapshot_files_url(obj),
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
            '<span class="snapshot-status-{}" style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 500; background: {}; color: {};">{}</span>',
            obj.status,
            bg_color,
            fg_color,
            obj.status.upper(),
        )

    @admin.display(
        description="Size",
        ordering="output_size",
        empty_value="",
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
            return ""

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
            '<a class="snapshot-original-url" href="{}"><code style="user-select: all;">{}</code></a>',
            obj.url,
            snapshot_url_text(obj.url),
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

    @admin.action(description="🗑️ Delete", permissions=["delete"])
    def delete_selected(
        self,
        request,
        queryset,
        *,
        confirmation_action="delete_selected",
        confirmation_selected=None,
        confirmation_across=True,
    ):
        from django.core import signing
        from django.template.response import TemplateResponse

        if not self.has_delete_permission(request):
            raise PermissionDenied
        if not request.user.is_superuser and confirmation_action == "delete_selected":
            # Staff retain related-model permission and protected-object checks.
            # Never let Django's confirmed action physically delete the rows.
            from django.contrib.admin.actions import delete_selected

            if request.POST.get("post"):
                _, _, permissions, protected = self.get_deleted_objects(queryset, request)
                if permissions:
                    raise PermissionDenied
                if not protected:
                    return self.delete_snapshots(request, queryset)
            return delete_selected(self, request, queryset)
        salt = "archivebox.snapshot-delete-selection"
        limit = 25000
        source_selection = (
            {"ids": sorted(confirmation_selected), "across": confirmation_across} if confirmation_selected is not None else None
        )
        if request.POST.get("post"):
            try:
                selection = signing.loads(request.POST.get("selection", ""), salt=salt, max_age=3600)
                ids = selection["ids"]
                if (
                    selection["user"] != str(request.user.pk)
                    or selection["scope"] != request.get_full_path()
                    or selection.get("action", "delete_selected") != confirmation_action
                    or selection.get("source_selection") != source_selection
                    or not isinstance(ids, list)
                    or not 0 < len(ids) <= limit
                ):
                    raise ValueError("Invalid selection")
            except (signing.BadSignature, KeyError, TypeError, ValueError):
                return HttpResponseBadRequest("Deletion confirmation expired or is invalid. Select snapshots again.")
            # Reapply current admin authorization/filtering, but never expand the
            # immutable confirmed set, including when select_across was used.
            from archivebox.api.webhook_membership import track_membership

            if not request.user.is_superuser:
                _, _, permissions, protected = self.get_deleted_objects(queryset.filter(pk__in=ids), request)
                if permissions:
                    raise PermissionDenied
                if protected:
                    return HttpResponseBadRequest("Protected snapshots cannot be deleted.")
            total = 0
            # One membership transition, even for limit-based smart folders;
            # each durable status update still uses a short bounded statement.
            with track_membership(lambda: ids):
                for start in range(0, len(ids), 400):
                    total += queryset.filter(pk__in=ids[start : start + 400]).exclude(status=Snapshot.DELETING_STATE).request_delete()
            messages.success(request, f"Queued {total} snapshots for deletion. The background runner will remove and verify their files.")
            return None

        # Do not call Django's nested deletion collector: cleanup is asynchronous,
        # and enumerating ArchiveResults/processes/files can take minutes on NAS.
        ids = [str(pk) for pk in queryset.order_by("pk").values_list("pk", flat=True)[: limit + 1]]
        if len(ids) > limit:
            return HttpResponseBadRequest(f"Select at most {limit:,} snapshots per deletion confirmation.")
        if not ids:
            if confirmation_action != "delete_selected":
                self.message_user(request, "No snapshots match the selection.", level=messages.INFO)
            return None
        if not request.user.is_superuser:
            _, _, permissions, protected = self.get_deleted_objects(queryset, request)
            if permissions:
                raise PermissionDenied
            if protected:
                return HttpResponseBadRequest("Protected snapshots cannot be deleted.")
        context = {
            **self.admin_site.each_context(request),
            "title": "Confirm snapshot deletion",
            "opts": self.model._meta,
            "selection": signing.dumps(
                {
                    "user": str(request.user.pk),
                    "scope": request.get_full_path(),
                    "ids": ids,
                    "action": confirmation_action,
                    "source_selection": source_selection,
                },
                salt=salt,
                compress=True,
            ),
            "count": len(ids),
            "preview": list(queryset.filter(pk__in=ids[:20]).order_by("pk").values_list("pk", "url")),
            "confirmation_action": confirmation_action,
            "confirmation_selected": confirmation_selected if confirmation_selected is not None else [ids[0]],
            "confirmation_across": confirmation_across,
            "confirmation_url": request.get_full_path(),
        }
        return TemplateResponse(request, "admin/core/snapshot/queue_deletion_confirmation.html", context)

    @admin.action(
        description="🗑️ Delete",
        permissions=["delete"],
    )
    def delete_snapshots(self, request, queryset):
        """Keep the rows until the runner removes and verifies their files."""
        total = queryset.request_delete()
        messages.success(
            request,
            f"Queued {total} snapshots for deletion. They remain visible as Deleting until ArchiveBox verifies their files are removed.",
        )

    @admin.action(
        description="+",
    )
    def add_tags(self, request, queryset):
        from archivebox.api.webhook_events import snapshot_tag_rules
        from archivebox.api.webhook_membership import track_membership
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

        tag_ids = [tag.pk for tag in tags]
        with track_membership(snapshot_ids):
            if snapshot_tag_rules("TAGGED", tag_ids).exists():
                for snapshot in queryset:
                    snapshot.add_tag_ids(tag_ids, emit_relationship=False)
            else:
                for tag_id in tag_ids:
                    SnapshotTag.objects.bulk_create(
                        [SnapshotTag(snapshot_id=sid, tag_id=tag_id) for sid in snapshot_ids],
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
        from archivebox.api.webhook_membership import track_membership
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

        with track_membership(snapshot_ids):
            deleted_count = SnapshotTag.remove_links(
                SnapshotTag.objects.filter(snapshot_id__in=snapshot_ids, tag_id__in=tag_ids),
                tag_ids,
            )

        messages.success(
            request,
            f"Removed {len(tags)} tag(s) from {num_snapshots} Snapshot(s) ({deleted_count} associations deleted).",
        )
