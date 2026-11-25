from functools import wraps
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from archivebox.config.constants import CONSTANTS
from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.misc.serve_static import RangedFileReader, _is_asgi_request, _stream_ranged_file_async
from archivebox.plugins.discovery import get_plugin_catalog

from .admin import ImporterRunAdmin
from .catalog import get_importer, get_importer_providers, get_importers
from .diagnostics import LOG_NAME, SCREENSHOT_NAME, artifact_path, diagnostics
from .forms import ImporterSourceForm
from .models import ImporterRun, ImporterSource
from .service import ACTIVE_STATUSES
from .settings_links import importer_settings_links


def importer_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Importer access requires a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


def page(request, template, context):
    return render(request, template, {**archivebox_admin.each_context(request), **context})


@importer_admin
@require_GET
def index(request):
    definitions = get_importers()
    sources = Paginator(
        ImporterSource.objects.select_related("persona")
        .defer("settings", "checkpoint", "account")
        .prefetch_related(
            Prefetch(
                "runs",
                queryset=ImporterRun.objects.defer("request", "result").order_by("-created_at", "-id")[:1],
                to_attr="latest_runs",
            ),
        ),
        50,
    ).get_page(request.GET.get("page"))
    sources.object_list = list(sources.object_list)
    for source in sources:
        source.definition = definitions.get((source.plugin, source.feed))
        source.latest_run = next(iter(source.latest_runs), None)
    return page(
        request, "importers/index.html", {"sources": sources, "providers": get_importer_providers(definitions), "title": "Importers"}
    )


@importer_admin
@require_http_methods(["GET", "POST"])
def configure(request, plugin=None, feed=None, source_id=None):
    source = get_object_or_404(ImporterSource, pk=source_id) if source_id else ImporterSource(created_by=request.user)
    try:
        definition = get_importer(source.plugin if source_id else plugin, source.feed if source_id else feed)
    except ValueError as error:
        raise Http404(str(error)) from error
    if source_id and source.runs.filter(status__in=ACTIVE_STATUSES).exists():
        messages.error(request, "Wait for the active run to finish, or pause it before editing.")
        return redirect(source)
    form = ImporterSourceForm(request.POST if request.method == "POST" else None, instance=source, definition=definition)
    if request.method == "POST" and form.is_valid():
        try:
            source = form.save()
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Importer saved. Use Dry Run to verify access and preview items.")
            return redirect(source)
    return page(
        request,
        "importers/configure.html",
        {
            "form": form,
            "source": source,
            "definition": definition,
            "title": "Configure importer",
            "settings_links": importer_settings_links(definition, source),
        },
    )


@importer_admin
@require_GET
def detail(request, source_id):
    source = get_object_or_404(ImporterSource.objects.select_related("persona", "folder"), pk=source_id)
    definition = get_importers().get((source.plugin, source.feed))
    history = ImporterRunAdmin(source_id).history(request)
    tag_names = Crawl.parse_tag_names(source.tags)
    tag_ids = dict(Tag.objects.filter(name__in=tag_names).values_list("name", "pk")) if tag_names else {}
    active = source.runs.filter(status__in=ACTIVE_STATUSES).exists()
    return page(
        request,
        "importers/detail.html",
        {
            "title": source.name,
            "source": source,
            "definition": definition,
            "cl": history,
            "source_id": source_id,
            "source_tags": [(name, tag_ids.get(name)) for name in tag_names],
            "activity_query": history.get_query_string({"p": history.page_num}),
            "active": active,
            "state_path": CONSTANTS.DATA_DIR / "importers" / str(source.pk) / "state",
        },
    )


@importer_admin
@require_POST
def action(request, source_id, action):
    source = get_object_or_404(ImporterSource, pk=source_id)
    try:
        from .service import source_action, delete_source

        if action == "delete":
            delete_source(source)
            messages.success(request, "Importer deleted. Existing captures are preserved.")
            return redirect("importers:index")
        result = source_action(source, action)
        if isinstance(result, ImporterRun):
            messages.success(request, f"{result.get_action_display()} queued. The ArchiveBox worker will process it.")
        else:
            messages.success(request, "Importer updated.")
    except ValueError as error:
        messages.error(request, str(error))
    return redirect(source)


@importer_admin
@require_GET
def run_detail(request, run_id):
    run = get_object_or_404(ImporterRun.objects.select_related("source__persona", "crawl").defer("request"), pk=run_id)
    return page(
        request,
        "importers/run.html",
        {
            **_run_settings_context(run),
            "title": run.get_action_display(),
            "run": run,
            "snapshots_changelist": archivebox_admin._registry[Snapshot].render_embedded_changelist(
                request,
                {"crawl_id": str(run.crawl_id)},
            )
            if run.crawl_id
            else "",
            "active": run.status in ACTIVE_STATUSES,
        },
    )


@importer_admin
@require_GET
def source_activity(request, source_id):
    # Materialize bounded DB reads before accessing files; never hold a cursor
    # across log reads, and keep them out of the initial HTML response entirely.
    source = get_object_or_404(ImporterSource.objects.only("id"), pk=source_id)
    history = ImporterRunAdmin(source_id).history(request, activity_loaded=True)
    active = source.runs.filter(status__in=ACTIVE_STATUSES).exists()
    return JsonResponse(
        {
            "html": render_to_string(
                "importers/history.html",
                {"cl": history, "source_id": source_id},
                request=request,
            ),
            "active": active,
        },
    )


def _run_settings_context(run):
    if run.status not in {ImporterRun.Status.NEEDS_LOGIN, ImporterRun.Status.FAILED}:
        return {}
    definition = get_importers().get((run.source.plugin, run.source.feed))
    return {
        "settings_links": importer_settings_links(definition, run.source),
        "needs_configuration": bool(definition and definition.settings_fields and run.status == ImporterRun.Status.NEEDS_LOGIN),
    }


@importer_admin
@require_GET
def run_activity(request, run_id):
    run = get_object_or_404(ImporterRun.objects.select_related("source", "crawl").defer("request"), pk=run_id)
    run.diagnostics = diagnostics(run)
    return JsonResponse(
        {
            "html": render_to_string(
                "importers/activity.html",
                {"run": run, **_run_settings_context(run)},
                request=request,
            ),
            "active": run.status in ACTIVE_STATUSES,
            "crawl_id": str(run.crawl_id) if run.crawl_id else None,
        },
    )


@importer_admin
@require_GET
def run_artifact(request, run_id, name, screenshot=False):
    run = get_object_or_404(ImporterRun.objects.only("source_id"), pk=run_id)
    try:
        stream = artifact_path(run, name, SCREENSHOT_NAME if screenshot else LOG_NAME).open("rb")
    except (ValueError, OSError) as error:
        raise Http404 from error
    response = FileResponse(stream, content_type="image/png" if screenshot else "text/plain; charset=utf-8")
    # Django otherwise consumes the entire sync FileResponse under ASGI;
    # private run logs can be large even when their activity preview is bounded.
    if _is_asgi_request(request):
        response.streaming_content = _stream_ranged_file_async(RangedFileReader(stream))
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@importer_admin
@require_GET
def run_json(request, run_id):
    run = get_object_or_404(ImporterRun, pk=run_id)
    # Deliberately exclude request settings and opaque checkpoints from export.
    return JsonResponse({"id": str(run.pk), "status": run.status, "action": run.action, "items": run.items, "message": run.message})


@importer_admin
@require_GET
def guide_image(request, plugin, feed, step):
    try:
        definition = get_importer(plugin, feed)
        return plugin_image(request, plugin, definition.setup[step]["image"])
    except (ValueError, KeyError, IndexError, OSError) as error:
        raise Http404 from error


def plugin_image(request, plugin, filename):
    root = get_plugin_catalog()[plugin].path.resolve()
    image = (root / Path(filename)).resolve()
    if not image.is_relative_to(root) or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise Http404
    stream = image.open("rb")
    response = FileResponse(stream)
    if _is_asgi_request(request):
        response.streaming_content = _stream_ranged_file_async(RangedFileReader(stream))
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@importer_admin
@require_GET
def brand_icon(request, plugin, feed):
    try:
        return plugin_image(request, plugin, get_importer(plugin, feed).icon)
    except (ValueError, KeyError, OSError) as error:
        raise Http404 from error


@importer_admin
@require_GET
def export_sources(request, format):
    from archivebox.core.exports import model_export_response

    sources = ImporterSource.objects.select_related("persona", "created_by", "folder")
    return model_export_response(
        request,
        (source.to_json() for source in sources.iterator(chunk_size=32)),
        format,
        name="importers",
    )


@importer_admin
@require_GET
def export_runs(request, source_id, format):
    from archivebox.core.exports import model_export_response

    source = get_object_or_404(ImporterSource, pk=source_id)
    runs = source.runs.select_related("source")
    return model_export_response(request, (run.to_json() for run in runs.iterator(chunk_size=32)), format, name="importer-runs")
