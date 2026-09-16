__package__ = "archivebox.crawls"

from typing import ClassVar

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django_object_actions import action

from archivebox.core.widgets import render_permissions_badge
from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.core.models import Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_META,
    PERMISSIONS_VALUES,
)
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.crawls.forms import CrawlAdminForm
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.progressmonitor.views import progress_endpoint
from archivebox.workers.models import RETRY_AT_MAX


class MaxDepthListFilter(admin.SimpleListFilter):
    title = "max depth"
    parameter_name = "max_depth"

    def lookups(self, request, model_admin):
        return [(str(depth), str(depth)) for depth in range(5)]

    def queryset(self, request, queryset):
        value = self.value()
        if value is not None and value.isdigit():
            return queryset.filter(max_depth=int(value))
        return queryset


class CrawlAdmin(ConfigEditorMixin, BaseModelAdmin):
    form = CrawlAdminForm
    change_form_template = "admin/crawls/crawl/change_form.html"
    list_select_related = ()
    paginator = AcceleratedPaginator
    show_full_result_count = False
    list_display = (
        "short_id",
        "permissions_badge",
        "created_at",
        "owner",
        "depth",
        "status_with_stop_reason",
        "pause_resume_control",
        "label",
        "notes",
        "urls_preview",
        "schedule_str",
        "retry_at",
        "num_archived_snapshots",
        "num_total_snapshots",
    )
    sort_fields = (
        "id",
        "created_at",
        "created_by",
        "max_depth",
        "label",
        "notes",
        "schedule_str",
        "status",
        "retry_at",
    )
    search_fields = (
        "id",
        "created_by__username",
        "max_depth",
        "label",
        "notes",
        "schedule_id",
        "status",
        "urls",
    )

    readonly_fields = ("created_at", "modified_at", "stop_reason_display")

    fieldsets = (
        (
            "URLs",
            {
                "fields": ("urls", "url_filters"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Overview",
            {
                "fields": (
                    ("label", "status", "retry_at", "schedule", "created_by", "created_at", "modified_at"),
                    ("max_depth",),
                    ("stop_reason_display",),
                    ("notes", "tags_editor"),
                ),
                "classes": ("card", "wide", "crawl-admin-overview"),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "classes": ("card", "wide", "crawl-admin-config"),
            },
        ),
    )
    add_fieldsets = (
        (
            "URLs",
            {
                "fields": ("urls", "url_filters"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Overview",
            {
                "fields": (
                    ("label", "status", "retry_at", "schedule", "created_by"),
                    ("max_depth",),
                    ("notes", "tags_editor"),
                ),
                "classes": ("card", "wide", "crawl-admin-overview"),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "classes": ("card", "wide", "crawl-admin-config"),
            },
        ),
    )

    list_filter = (MaxDepthListFilter, "schedule", "created_by", "status", "retry_at")
    ordering = ("-created_at", "-retry_at")
    list_per_page = 50
    actions = (
        "pause_selected_crawls",
        "resume_selected_crawls",
        "seal_selected_crawls",
        "delete_selected_batched",
        "set_crawl_permissions",
    )
    change_actions = ("recrawl",)

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self.crawl_admin_base_config = None
        self.stop_reason_cache = {}

    class Media:
        css: ClassVar[dict[str, tuple[str, ...]]] = {"all": ("admin/crawls/crawl_change.css",)}
        js: ClassVar[tuple[str, ...]] = ("admin/crawls/crawl_admin.js",)

    def changelist_view(self, request, extra_context=None):
        self.request = request
        self.crawl_admin_base_config = request.archivebox_config
        self.stop_reason_cache = {}
        response = super().changelist_view(request, extra_context)
        if not isinstance(response, TemplateResponse):
            return response
        cl = response.context_data.get("cl")
        if cl is not None and not self.should_annotate_snapshot_counts(request):
            self.hydrate_visible_snapshot_counts(cl.result_list)
        return response

    def should_annotate_snapshot_counts(self, request):
        ordering = request.GET.get("o", "")
        if not ordering:
            return False
        list_display = list(self.get_list_display(request))
        count_positions = {
            str(list_display.index("num_archived_snapshots") + 1),
            str(list_display.index("num_total_snapshots") + 1),
        }
        return any(part.lstrip("-") in count_positions for part in ordering.split("."))

    def hydrate_visible_snapshot_counts(self, crawls):
        crawl_list = list(crawls)
        crawl_ids = [crawl.pk for crawl in crawl_list]
        if not crawl_ids:
            return
        counts = Snapshot.crawl_total_and_status_counts(crawl_ids, status=Snapshot.StatusChoices.SEALED)
        for crawl in crawl_list:
            row = counts.get(str(crawl.pk), {})
            crawl.num_snapshots_cached = row.get("total", 0)
            crawl.num_archived_snapshots_cached = row.get("status", 0)

    def get_queryset(self, request):
        """Keep joins page-local while computing per-row snapshot counts in the page query."""
        queryset = (
            super()
            .get_queryset(request)
            .prefetch_related(
                "created_by",
                "persona",
                "schedule__template",
            )
        )
        if self.should_annotate_snapshot_counts(request):
            queryset = queryset.annotate(
                num_snapshots_cached=Snapshot.crawl_count_expr(),
                num_archived_snapshots_cached=Snapshot.crawl_count_expr(status=Snapshot.StatusChoices.SEALED),
            )
        return queryset

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        self.crawl_admin_base_config = request.archivebox_config
        self.stop_reason_cache = {}
        crawl = self.get_object(request, object_id)
        if crawl:
            self.hydrate_visible_snapshot_counts([crawl])
        extra_context = {
            **(extra_context or {}),
            "crawl_stop_reason": self.stop_reason_for_crawl(crawl) if crawl else "",
            "crawl_snapshots_changelist": self.snapshots_changelist(crawl) if crawl else "",
        }
        if crawl and crawl.status in {
            Crawl.StatusChoices.QUEUED,
            Crawl.StatusChoices.STARTED,
            Crawl.StatusChoices.PAUSED,
        }:
            extra_context["progress_auto_expand"] = True
            extra_context["progress_endpoint"] = progress_endpoint("crawl", crawl.id)
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        self.request = request
        return super().add_view(request, form_url, extra_context)

    def get_fieldsets(self, request, obj=None):
        return self.fieldsets if obj else self.add_fieldsets

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/snapshot/<path:snapshot_id>/delete/",
                self.admin_site.admin_view(self.delete_snapshot_view),
                name="crawls_crawl_snapshot_delete",
            ),
            path(
                "<path:object_id>/snapshot/<path:snapshot_id>/exclude-domain/",
                self.admin_site.admin_view(self.exclude_domain_view),
                name="crawls_crawl_snapshot_exclude_domain",
            ),
            path(
                "<path:object_id>/set-permissions/",
                self.admin_site.admin_view(self.set_permissions_view),
                name="crawls_crawl_set_permissions",
            ),
        ]
        return custom_urls + urls

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="Delete")
    def delete_selected_batched(self, request, queryset):
        """Delete crawls in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list("pk", flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Crawl.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(request, f"Successfully deleted {total} crawls ({deleted_count} total objects including related records).")

    @admin.action(description="Pause")
    def pause_selected_crawls(self, request, queryset):
        # Admin changelist actions must stay set-based. Calling crawl.pause()
        # here fans out into per-crawl Snapshot/ArchiveResult writes and can
        # hold SQLite behind the request for minutes on large archives. The
        # Crawl row is the scheduler signal; the runner observes PAUSED and
        # owns child-row lifecycle work.
        paused = queryset.exclude(status__in=Crawl.INACTIVE_STATES).update(
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
            modified_at=timezone.now(),
        )
        if paused:
            messages.success(request, f"Paused {paused} crawl(s). The runner will stop scheduling new work on the next sweep.")
        else:
            messages.warning(request, "No active crawls were selected to pause.")

    @admin.action(description="Resume")
    def resume_selected_crawls(self, request, queryset):
        # Keep resume symmetrical with pause: one tight scheduler UPDATE, no
        # save() hooks and no child fanout in the request path. Paused child
        # rows become runnable through their own resume/maintenance paths.
        resumed = queryset.filter(status__in=Crawl.INACTIVE_STATES).update(
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            modified_at=timezone.now(),
        )
        if resumed:
            messages.success(request, f"Resumed {resumed} crawl(s). The runner will pick them up on the next sweep.")
        else:
            messages.warning(request, "No paused or sealed crawls were selected to resume.")

    @admin.action(description="Seal")
    def seal_selected_crawls(self, request, queryset):
        now = timezone.now()
        crawl_ids = list(queryset.exclude(status=Crawl.StatusChoices.SEALED).values_list("pk", flat=True))
        if not crawl_ids:
            messages.warning(request, "No unsealed crawls were selected to seal.")
            return

        Snapshot.objects.filter(
            crawl_id__in=crawl_ids,
            status__in=Snapshot.OPEN_STATES,
        ).filter(
            Q(retry_at__isnull=True) | Q(retry_at__gt=now),
        ).update(
            retry_at=now,
            modified_at=now,
        )
        sealed = (
            Crawl.objects.filter(pk__in=crawl_ids)
            .exclude(status=Crawl.StatusChoices.SEALED)
            .update(
                status=Crawl.StatusChoices.SEALED,
                retry_at=now,
                modified_at=now,
            )
        )
        messages.success(request, f"Sealed {sealed} crawl(s). The runner will finish cleanup on the next sweep.")

    @admin.action(description="Permissions ▾")
    def set_crawl_permissions(self, request, queryset):
        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in PERMISSIONS_VALUES:
            messages.error(request, "Choose a valid permissions value.")
            return
        updated = self.update_crawl_permissions(queryset, permissions)
        messages.success(request, f"Set permissions to {permissions} on {updated} crawl(s).")

    def update_crawl_permissions(self, queryset, permissions):
        now = timezone.now()
        updated = 0
        batch = []
        crawls_to_update = []
        for crawl in queryset.only("id", "config", "permissions").iterator(chunk_size=500):
            old_permissions = crawl.permissions
            config = dict(crawl.config or {})
            config["PERMISSIONS"] = permissions
            crawl.config = config
            crawl.modified_at = now
            crawls_to_update.append((crawl, old_permissions))
            batch.append(crawl)
            if len(batch) >= 500:
                Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
                updated += len(batch)
                batch.clear()
        if batch:
            Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
            updated += len(batch)
        for crawl, old_permissions in crawls_to_update:
            crawl.update_child_snapshot_permissions(old_permissions, permissions)
        return updated

    @action(label="Recrawl", description="Create a new crawl with the same settings", methods=("POST",))
    def recrawl(self, request, obj):
        """Duplicate this crawl as a new crawl with the same URLs and settings."""

        # Validate URLs (required for crawl to start)
        if not obj.urls:
            messages.error(request, "Cannot recrawl: original crawl has no URLs.")
            return redirect("admin:crawls_crawl_change", obj.id)

        new_crawl = Crawl.create_scheduler_row(
            urls=obj.urls,
            max_depth=obj.max_depth,
            tags_str=obj.tags_str,
            config=obj.config,
            schedule=obj.schedule,
            label=f"{obj.label} (recrawl)" if obj.label else "",
            notes=obj.notes,
            created_by=request.user,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        messages.success(request, f"Created new crawl {new_crawl.id} with the same settings. It will start processing shortly.")

        return redirect("admin:crawls_crawl_change", new_crawl.id)

    @admin.display(description="Stop Reason")
    def stop_reason_display(self, obj):
        reason = self.stop_reason_for_crawl(obj) if obj else ""
        if not reason:
            return mark_safe('<span class="crawl-stop-reason crawl-stop-reason--empty">None</span>')
        return format_html('<span class="crawl-stop-reason">{}</span>', reason)

    def stop_reason_for_crawl(self, obj):
        if obj.pk in self.stop_reason_cache:
            return self.stop_reason_cache[obj.pk]

        output_dir = obj.output_dir
        config = self.limit_config_for_crawl(obj, output_dir)
        reason = obj.stop_reason(
            config=config,
            output_dir=output_dir,
            num_snapshots=obj.num_snapshots_cached,
            num_sealed_snapshots=obj.num_archived_snapshots_cached,
        )
        self.stop_reason_cache[obj.pk] = reason
        return reason

    def limit_config_for_crawl(self, obj, output_dir):
        from archivebox.config.common import get_config

        return get_config(crawl=obj).for_crawl_runtime(
            crawl=obj,
            persona=obj.resolve_persona(),
            crawl_output_dir=output_dir,
        )

    @admin.display(description="Status", ordering="status")
    def status_with_stop_reason(self, obj):
        status = "PAUSED" if obj.is_paused else str(obj.status or "").upper()
        reason = self.stop_reason_for_crawl(obj) if obj.is_paused or obj.status == Crawl.StatusChoices.SEALED else ""
        if reason:
            reason_label = reason.removeprefix("crawl_").replace("_", " ")
            return format_html(
                '<span class="crawl-status-group"><span class="crawl-status crawl-status--{}">{}</span><span class="crawl-status-reason crawl-status-reason--{}">{}</span></span>',
                obj.status,
                status,
                reason,
                reason_label,
            )
        return format_html('<span class="crawl-status crawl-status--{}">{}</span>', obj.status, status)

    @admin.display(description="ID", ordering="id")
    def short_id(self, obj):
        short_id = str(obj.pk)[-8:]
        return format_html('<a href="{}">{}</a>', obj.admin_change_url, short_id)

    @admin.display(description="Owner", ordering="created_by")
    def owner(self, obj):
        return obj.created_by

    @admin.display(description="Depth", ordering="max_depth")
    def depth(self, obj):
        return obj.max_depth

    @admin.display(description="👁", ordering="permissions")
    def permissions_badge(self, obj):
        permissions = obj.permissions
        return render_permissions_badge(
            permissions,
            url=reverse(f"{self.admin_site.name}:crawls_crawl_set_permissions", args=[obj.pk]),
            object_name="crawl",
        )

    @admin.display(description="Pause")
    def pause_resume_control(self, obj):
        if obj.is_paused or obj.status == Crawl.StatusChoices.SEALED:
            reason = "paused" if obj.is_paused else (self.stop_reason_for_crawl(obj) or "sealed")
            return format_html(
                '<button type="button" class="button crawl-resume-row" data-crawl-id="{}" title="Resume crawl. Stop reason: {}">Resume</button>',
                obj.pk,
                reason,
            )
        return format_html(
            '<button type="button" class="button crawl-pause-row" data-crawl-id="{}" title="Pause crawl">Pause</button>',
            obj.pk,
        )

    @admin.display(description="Archived", ordering="num_archived_snapshots_cached")
    def num_archived_snapshots(self, obj):
        return obj.num_archived_snapshots_cached

    @admin.display(description="Snapshots", ordering="num_snapshots_cached")
    def num_total_snapshots(self, obj):
        return obj.num_snapshots_cached

    @admin.display(description="Snapshots")
    def snapshots_changelist(self, obj):
        return self.admin_site._registry[Snapshot].render_embedded_changelist(
            self.request,
            filters={"crawl_id": str(obj.pk)},
            title="Snapshots in this crawl",
        )

    def delete_snapshot_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)

        if snapshot.status == Snapshot.StatusChoices.STARTED:
            snapshot.cancel_running_hooks()

        removed_urls = crawl.prune_url(snapshot.url)
        snapshot.delete()
        return JsonResponse(
            {
                "ok": True,
                "snapshot_id": str(snapshot.id),
                "removed_urls": removed_urls,
            },
        )

    def exclude_domain_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)
        result = crawl.exclude_domain(snapshot.url)
        return JsonResponse(
            {
                "ok": True,
                **result,
            },
        )

    def set_permissions_view(self, request: HttpRequest, object_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in PERMISSIONS_VALUES:
            return HttpResponseBadRequest("Invalid permissions value")

        crawl = get_object_or_404(Crawl, pk=object_id)
        self.update_crawl_permissions(Crawl.objects.filter(pk=crawl.pk), permissions)
        icon, label, fg, bg = PERMISSIONS_META[permissions]
        return JsonResponse({"permissions": permissions, "icon": icon, "label": label, "fg": fg, "bg": bg})

    @admin.display(description="Schedule", ordering="schedule")
    def schedule_str(self, obj):
        if not obj.schedule:
            return mark_safe("<i>None</i>")
        return format_html('<a href="{}">{}</a>', obj.schedule.admin_change_url, obj.schedule)

    @admin.display(description="URLs", ordering="urls")
    def urls_preview(self, obj):
        first_url = next((line.strip() for line in (obj.urls or "").splitlines() if line.strip() and not line.strip().startswith("#")), "")
        return first_url[:80] + "..." if len(first_url) > 80 else first_url


class CrawlScheduleAdmin(BaseModelAdmin):
    change_form_template = "admin/crawls/crawlschedule/change_form.html"

    class Media:
        css: ClassVar[dict[str, tuple[str, ...]]] = {"all": ("admin/crawls/crawl_change.css",)}

    list_display = ("id", "created_at", "created_by", "label", "notes", "template_str", "crawls", "num_crawls", "num_snapshots")
    sort_fields = ("id", "created_at", "created_by", "label", "notes", "template_str")
    search_fields = ("id", "created_by__username", "label", "notes", "schedule_id", "template_id", "template__urls")

    readonly_fields = ("created_at", "modified_at", "crawls")
    autocomplete_fields = ("template", "created_by")

    fieldsets = (
        (
            "Schedule Info",
            {
                "fields": ("label", "notes"),
                "classes": ("card",),
            },
        ),
        (
            "Configuration",
            {
                "fields": ("schedule", "template"),
                "classes": ("card",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
        (
            "Crawls",
            {
                "fields": ("crawls",),
                "classes": ("card", "wide"),
            },
        ),
    )

    list_filter = ("created_by",)
    ordering = ("-created_at",)
    list_per_page = 100
    actions = ("delete_selected",)

    def get_queryset(self, request):
        self.request = request
        return (
            super()
            .get_queryset(request)
            .select_related("created_by", "template")
            .annotate(
                crawl_count=Count("crawl", distinct=True),
                snapshot_count=Count("crawl__snapshot_set", distinct=True),
            )
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        schedule = self.get_object(request, object_id)
        extra_context = {**(extra_context or {})}
        if schedule:
            extra_context["schedule_snapshots_changelist"] = self.admin_site._registry[Snapshot].render_embedded_changelist(
                request,
                filters={"crawl__schedule__id__exact": str(schedule.pk)},
                title="Snapshots in this schedule",
                default_search_mode="meta",
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        return redirect("/add/#schedule")

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return tuple(fieldset for fieldset in self.fieldsets if fieldset[0] != "Crawls")
        return self.fieldsets

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Template", ordering="template")
    def template_str(self, obj):
        return format_html('<a href="{}">{}</a>', obj.template.admin_change_url, obj.template)

    @admin.display(description="# Crawls", ordering="crawl_count")
    def num_crawls(self, obj):
        count = obj.__dict__.get("crawl_count")
        if count is None:
            count = obj.crawl_set.count()
        return count

    @admin.display(description="# Snapshots", ordering="snapshot_count")
    def num_snapshots(self, obj):
        count = obj.__dict__.get("snapshot_count")
        if count is None:
            count = Snapshot.objects.filter(crawl__schedule=obj).count()
        return count

    def crawls(self, obj):
        return format_html_join(
            "<br/>",
            ' - <a href="{}">{}</a>',
            ((crawl.admin_change_url, crawl) for crawl in obj.crawl_set.all().order_by("-created_at")[:20]),
        ) or mark_safe("<i>No Crawls yet...</i>")


def register_admin(admin_site):
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
