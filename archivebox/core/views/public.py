from typing import ClassVar

from django.core.paginator import InvalidPage
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic.list import ListView

from archivebox.config import VERSION
from archivebox.config.common import (
    get_request_config,
)
from archivebox.core.models import ArchiveResult, Snapshot, SnapshotTag
from archivebox.core.permissions import (
    PERMISSIONS_PRIVATE,
    PERMISSIONS_PUBLIC,
    PERMISSIONS_UNLISTED,
    public_snapshots_queryset,
)
from archivebox.core.routes_util import (
    build_web_url,
)
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.search.config import (
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
)
from archivebox.search.views import get_cached_public_search_state

from .replay_auth import _admin_login_redirect_or_forbidden


class HomepageView(View):
    def get(self, request):
        request_config = get_request_config(request)
        if not request_config.BASE_URL:
            return _admin_login_redirect_or_forbidden(request)

        if request.user.is_authenticated and request_config.CONTROL_PLANE_ENABLED:
            return redirect("/admin/core/snapshot/")

        if request_config.PUBLIC_INDEX:
            return redirect("/public")

        return _admin_login_redirect_or_forbidden(request)


class PublicIndexView(ListView):
    template_name = "public_index.html"
    model = Snapshot
    ordering: ClassVar[list[str]] = ["-bookmarked_at", "-created_at"]
    paginator_class = AcceleratedPaginator
    public_page_scan_chunk_size = 50

    def get_paginate_by(self, queryset):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        return runtime_config.SNAPSHOTS_PER_PAGE

    def _base_public_snapshot_fields(self) -> tuple[str, ...]:
        return (
            "id",
            "created_at",
            "modified_at",
            "url",
            "timestamp",
            "bookmarked_at",
            "title",
            "downloaded_at",
            "status",
            "output_size",
            "permissions",
        )

    def _ordered_public_page_from_order_index(self, *, page_number: int, page_size: int) -> list[Snapshot] | None:
        target_count = page_number * page_size
        public_snapshots: list[Snapshot] = []
        scanned = 0
        chunk_size = max(self.public_page_scan_chunk_size, page_size)
        ordered_snapshots = Snapshot.objects.order_by(*self.ordering).only(*self._base_public_snapshot_fields())

        while len(public_snapshots) < target_count:
            chunk = list(ordered_snapshots[scanned : scanned + chunk_size])
            if not chunk:
                break
            scanned += len(chunk)
            public_snapshots.extend(snapshot for snapshot in chunk if snapshot.permissions == PERMISSIONS_PUBLIC)

        start = (page_number - 1) * page_size
        return public_snapshots[start:target_count]

    def paginate_queryset(self, queryset, page_size):
        if self.request.GET.get("q", default="").strip():
            return super().paginate_queryset(queryset, page_size)

        public_count = self.get_exact_public_snapshot_count()
        paginator = self.get_paginator(range(public_count), page_size)
        page_kwarg = self.kwargs.get(self.page_kwarg)
        page_query = self.request.GET.get(self.page_kwarg)
        page_number = page_kwarg or page_query or 1

        try:
            page = paginator.page(page_number)
        except InvalidPage as err:
            raise Http404(f"Invalid page ({page_number}): {err}") from err

        object_list = self._ordered_public_page_from_order_index(page_number=page.number, page_size=page_size)
        page.object_list = object_list
        return paginator, page, object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        search_mode = get_search_mode(self.request.GET.get("search_mode"), config=runtime_config)
        search_mode_backend = get_search_mode_backend(search_mode, config=runtime_config)
        query = self.request.GET.get("q", default="").strip()
        public_search_state = self.__dict__.get("public_search_state")
        public_search_pending = bool(query and (public_search_state is None or not public_search_state.get("done")))
        context = {
            **super().get_context_data(**kwargs),
            "VERSION": VERSION,
            "CONFIG": runtime_config,
            "COMMIT_HASH": runtime_config.COMMIT_HASH,
            "FOOTER_INFO": runtime_config.FOOTER_INFO,
            "WEB_BASE_URL": build_web_url(request=self.request, config=runtime_config),
            "search_mode": search_mode,
            "search_mode_options": get_search_mode_options(config=runtime_config),
            "public_search_stream_pending": public_search_pending,
        }
        context["show_search_index_hint"] = bool(
            query
            and not public_search_pending
            and get_search_mode_base(search_mode, config=runtime_config) == "deep"
            and search_mode_backend
            and context["paginator"].count == 0,
        )
        snapshots = list(context.get("object_list") or ())
        icons_by_snapshot: dict[str, set[str]] = {str(snapshot.id): set() for snapshot in snapshots}
        tag_names_by_snapshot: dict[str, list[str]] = {str(snapshot.id): [] for snapshot in snapshots}
        preview_paths_by_snapshot: dict[str, list[tuple[int, int, str]]] = {str(snapshot.id): [] for snapshot in snapshots}
        favicon_paths_by_snapshot: dict[str, list[str]] = {str(snapshot.id): [] for snapshot in snapshots}
        progress_by_snapshot: dict[str, dict[str, int]] = {
            str(snapshot.id): {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "running": 0,
                "skipped": 0,
                "noresults": 0,
            }
            for snapshot in snapshots
        }
        if icons_by_snapshot:
            for snapshot_id, tag_name in (
                SnapshotTag.objects.filter(snapshot_id__in=icons_by_snapshot.keys())
                .order_by("tag__name")
                .values_list("snapshot_id", "tag__name")
                .iterator(chunk_size=1000)
            ):
                tag_names_by_snapshot[str(snapshot_id)].append(tag_name)

            preview_plugin_order = {
                "screenshot": 0,
                "chrome_extension_screenshot": 1,
            }
            preview_candidates = {
                "screenshot": ("screenshot.png",),
                "chrome_extension_screenshot": ("screenshot-1.png", "screenshot.png"),
            }

            def result_output_path(result: ArchiveResult, filename: str) -> str | None:
                output_files = result.output_files or {}
                file_info = output_files.get(filename)
                if not isinstance(file_info, dict) or int(file_info.get("size") or 0) <= 0:
                    return None
                if file_info.get("root_relative"):
                    return filename
                return f"{result.plugin}/{filename}"

            for snapshot_id, plugin, status in (
                ArchiveResult.objects.filter(
                    snapshot_id__in=icons_by_snapshot.keys(),
                )
                .exclude(plugin="")
                .values_list("snapshot_id", "plugin", "status")
                .iterator(chunk_size=1000)
            ):
                snapshot_key = str(snapshot_id)
                progress = progress_by_snapshot[snapshot_key]
                progress["total"] += 1
                if status == ArchiveResult.StatusChoices.SUCCEEDED:
                    icons_by_snapshot[snapshot_key].add(plugin)
                    progress["succeeded"] += 1
                elif status == ArchiveResult.StatusChoices.FAILED:
                    progress["failed"] += 1
                elif status == ArchiveResult.StatusChoices.STARTED:
                    progress["running"] += 1
                elif status == ArchiveResult.StatusChoices.SKIPPED:
                    progress["skipped"] += 1
                elif status == ArchiveResult.StatusChoices.NORESULTS:
                    progress["noresults"] += 1

            for result in (
                ArchiveResult.objects.filter(
                    snapshot_id__in=icons_by_snapshot.keys(),
                    status=ArchiveResult.StatusChoices.SUCCEEDED,
                    plugin__in=(*preview_candidates, "favicon"),
                )
                .only("snapshot_id", "plugin", "output_files")
                .iterator(chunk_size=1000)
            ):
                snapshot_key = str(result.snapshot_id)
                if result.plugin in preview_candidates:
                    plugin_rank = preview_plugin_order[result.plugin]
                    for filename_rank, filename in enumerate(preview_candidates[result.plugin]):
                        output_path = result_output_path(result, filename)
                        if output_path:
                            preview_paths_by_snapshot[snapshot_key].append((plugin_rank, filename_rank, output_path))
                elif result.plugin == "favicon":
                    output_path = result_output_path(result, "favicon.ico")
                    if output_path:
                        favicon_paths_by_snapshot[snapshot_key].append(output_path)

        for snapshot in snapshots:
            snapshot._icons_compact = True
            snapshot._icons_archive_results = icons_by_snapshot.get(str(snapshot.id), set())
            snapshot._icons_progress_stats = progress_by_snapshot.get(str(snapshot.id), {})
            snapshot.num_outputs_cached = snapshot._icons_progress_stats.get("succeeded", 0)
            snapshot._tags_str_cached = ",".join(tag_names_by_snapshot.get(str(snapshot.id), []))
            snapshot._public_preview_paths = [
                output_path for _plugin_rank, _filename_rank, output_path in sorted(preview_paths_by_snapshot.get(str(snapshot.id), []))
            ]
            snapshot._public_favicon_paths = favicon_paths_by_snapshot.get(str(snapshot.id), [])
            snapshot._is_archived_cached = bool(snapshot.downloaded_at or snapshot.status == Snapshot.StatusChoices.SEALED)
        context["object_list"] = snapshots
        return context

    def get_exact_public_snapshot_count(self) -> int:
        hidden_count = Snapshot.objects.filter(permissions=PERMISSIONS_PRIVATE).count()
        hidden_count += Snapshot.objects.filter(permissions=PERMISSIONS_UNLISTED).count()
        return Snapshot.objects.count() - hidden_count

    def get_queryset(self, **kwargs):
        qs = public_snapshots_queryset(super().get_queryset(**kwargs)).only(*self._base_public_snapshot_fields())
        query = self.request.GET.get("q", default="").strip()

        if not query:
            return qs

        cached_state = get_cached_public_search_state(self.request)
        self.public_search_state = cached_state
        if cached_state is not None:
            cached_ids = cached_state.get("ids") or []
            if not cached_ids:
                return qs.none()
            search_rank = Case(
                *(When(pk=snapshot_id, then=Value(index)) for index, snapshot_id in enumerate(cached_ids)),
                output_field=IntegerField(),
            )
            return qs.filter(pk__in=cached_ids).annotate(search_rank=search_rank).order_by("search_rank", *self.ordering)

        return qs.none()

    def get(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/admin/core/snapshot/")
        if get_request_config(self.request).PUBLIC_INDEX:
            response = super().get(*args, **kwargs)
            return response
        else:
            return _admin_login_redirect_or_forbidden(self.request)


class HealthCheckView(View):
    """
    A Django view that renders plain text "OK" for service discovery tools
    """

    def get(self, request):
        """
        Handle a GET request
        """
        response = HttpResponse("OK", content_type="text/plain", status=200)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Expose-Headers"] = "X-ArchiveBox-Health"
        response["X-ArchiveBox-Health"] = "OK"
        return response
