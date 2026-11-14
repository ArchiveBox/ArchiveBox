"""Derived snapshot exports shared by library views, API requests and the CLI."""

import csv
import hashlib
import json
from copy import copy
from pathlib import Path

from django.contrib import admin
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.apps import apps
from django.utils.dateparse import parse_datetime
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import resolve, reverse
from django.views.decorators.cache import never_cache

EXPORT_FORMATS = {"rss": "RSS", "csv": "CSV", "jsonl": "JSONL", "html_zip": "Static HTML ZIP", "wacz": "Unified WACZ"}
ALL_EXPORT_FORMATS = {**EXPORT_FORMATS, "html": "Static HTML", "replay": "WACZ + ReplayWeb.page"}
ARCHIVE_FORMATS = {"html_zip", "wacz", "html", "replay"}
MAX_ARCHIVE_BYTES = 4 * 1024**3
EXPORT_FIELDS = (
    "type",
    "schema_version",
    "id",
    "crawl_id",
    "url",
    "title",
    "tags",
    "bookmarked_at",
    "created_at",
    "modified_at",
    "downloaded_at",
    "timestamp",
    "depth",
    "status",
    "fs_version",
    "archive_size",
    "output_size",
)
CREDENTIAL_PARAMETERS = {
    "api_key",
    "key",
    "token",
    "api_token",
    "access_token",
    "password",
    "auth",
    "authorization",
    "csrfmiddlewaretoken",
    "csrf_token",
    "sessionid",
    "cookie",
}
OMITTED_PARAMETERS = CREDENTIAL_PARAMETERS | {
    "p",
    "page",
    "per_page",
    "limit",
    "offset",
    "_popup",
    "_to_field",
    "_embedded",
    "job",
    "format",
    "directory",
    "session",
}


def normalize_export_query(query):
    source = QueryDict(query) if isinstance(query, str) else query
    source = source or {}
    result = QueryDict(mutable=True)
    entries = source.lists() if hasattr(source, "lists") else source.items()
    for key, values in sorted(entries):
        if key.lower() not in OMITTED_PARAMETERS and values is not None:
            result.setlist(key, [str(value) for value in (values if isinstance(values, (list, tuple)) else [values])])
    return result


def get_export_queryset(query, *, user=None, public_only=True, config=None):
    from archivebox.config.common import get_config
    from archivebox.core.admin_site import archivebox_admin
    from archivebox.core.models import Snapshot

    request = HttpRequest()
    request.path = "/admin/core/snapshot/"
    request.GET = normalize_export_query(query)
    request.user = user or AnonymousUser()
    request.archivebox_config = config or get_config()
    request.resolver_match = resolve(request.path)
    model_admin = archivebox_admin._registry[Snapshot]
    if public_only:
        allowed = {
            "q",
            "search_mode",
            "o",
            "id__in",
            "id__exact",
            "crawl__id__exact",
            "crawl_id__exact",
            "crawl_id",
            "url__regex",
            "url__startswith",
            "url__icontains",
            "crawl__created_by__id__exact",
            "crawl__created_by__isnull",
            "created_at__gte",
            "created_at__lt",
            "created_at__lte",
            "created_at__isnull",
            "downloaded_at__gte",
            "downloaded_at__lt",
            "downloaded_at__isnull",
        } | {
            spec.parameter_name
            for spec in model_admin.get_list_filter(request)
            if isinstance(spec, type) and issubclass(spec, admin.SimpleListFilter)
        }
        if set(request.GET) - allowed:
            raise ValueError("Invalid public snapshot filters.")
    return model_admin.get_list_queryset(request, public_only=public_only)


def selection_digest(snapshots):
    digest = hashlib.sha256()
    ids = snapshots.values_list("pk", flat=True) if hasattr(snapshots, "values_list") else snapshots
    for pk in sorted(str(pk) for pk in ids):
        digest.update(str(pk).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def write_snapshot_metadata(snapshots, format, output, *, request=None):
    from archivebox.cli.archivebox_snapshot import iter_snapshot_json

    if format == "rss":
        from archivebox.api.v1_core import _snapshots_rss_response

        if request is None:
            from archivebox.config.common import get_config
            from urllib.parse import urlsplit

            from io import BytesIO
            from django.core.handlers.wsgi import WSGIRequest

            origin = urlsplit(get_config().BASE_URL or "http://localhost:8000")
            request = WSGIRequest(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/admin/core/snapshot/feed/",
                    "SERVER_NAME": origin.hostname,
                    "SERVER_PORT": str(origin.port or (443 if origin.scheme == "https" else 80)),
                    "HTTP_HOST": origin.netloc,
                    "wsgi.url_scheme": origin.scheme,
                    "wsgi.input": BytesIO(),
                },
            )
            request.user = AnonymousUser()
            request.archivebox_config = get_config()
        request = copy(request)
        request.GET = normalize_export_query(request.GET)
        response = _snapshots_rss_response(request, snapshots=snapshots.select_related("crawl__created_by").prefetch_related("tags"))
        output.write(response.content.decode())
        return
    if format not in {"csv", "jsonl"}:
        raise ValueError("Select RSS, CSV, or JSONL.")
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS) if format == "csv" else None
    if writer:
        writer.writeheader()
    for record in iter_snapshot_json(snapshots):
        row = {field: record[field] for field in EXPORT_FIELDS}
        if writer:
            writer.writerow(row)
        else:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def _principal(request, *, session_authorized=False):
    from archivebox.api.auth import auth_using_token, token_from_request
    from archivebox.core.admin_site import archivebox_admin
    from archivebox.core.models import Snapshot

    key = token_from_request(request)
    if key:
        user = auth_using_token(key, request=request)
        if user is None or not user.is_active:
            return None, HttpResponse(status=401)
    elif session_authorized:
        user = request.user
    else:
        return AnonymousUser(), None
    selected = copy(request)
    selected.user = user
    if not archivebox_admin.has_permission(selected) or not archivebox_admin._registry[Snapshot].has_view_permission(selected):
        return None, HttpResponse(status=403)
    return user, None


def _job_urls(process, *, api=False):
    base = f"/api/v1/core/snapshots/exports/{process.pk}" if api else reverse("admin:core_snapshot_export_job", args=[process.pk])
    return {"status_url": base, "download_url": base.rstrip("/") + "/download/", "cancel_url": base.rstrip("/") + "/cancel/"}


def _job_data(process, *, api=False):
    return {
        "id": str(process.pk),
        "status": process.status,
        "exit_code": process.exit_code,
        "result": process.export_report,
        "can_cancel": "--public-only" not in process.cmd,
        **_job_urls(process, api=api),
    }


@never_cache
def snapshot_export_view(request, format="rss", *, api=False, session_authorized=False):
    from archivebox.config import CONSTANTS

    format = request.POST.get("format", format) if request.method == "POST" else format
    if format not in ALL_EXPORT_FORMATS or (format in ARCHIVE_FORMATS and not apps.is_installed("archivebox.domains")):
        return HttpResponse(status=404)
    allowed_methods = ["GET", "HEAD", "POST"] if format in ARCHIVE_FORMATS else ["GET", "HEAD"]
    if request.method not in allowed_methods:
        from django.http import HttpResponseNotAllowed

        return HttpResponseNotAllowed(allowed_methods)
    user, error = _principal(
        request,
        session_authorized=session_authorized or (request.method == "POST" and request.POST.get("session") == "1"),
    )
    if error is not None:
        return error
    public_only = not user.is_authenticated
    if public_only and format in {"html", "replay"}:
        return HttpResponse(status=403)
    query = normalize_export_query(request.GET)
    try:
        snapshots = get_export_queryset(query, user=user, public_only=public_only, config=getattr(request, "archivebox_config", None))
    except (IncorrectLookupParameters, SuspiciousOperation, ValidationError, ValueError):
        return HttpResponseBadRequest("Invalid snapshot filters.")
    if format not in ARCHIVE_FORMATS:
        response = HttpResponse(
            content_type={"rss": "application/rss+xml; charset=utf-8", "csv": "text/csv; charset=utf-8", "jsonl": "application/x-ndjson"}[
                format
            ],
        )
        if format != "rss":
            response["Content-Disposition"] = f'attachment; filename="snapshots.{format}"'
        write_snapshot_metadata(snapshots, format, response, request=request)
        response["Referrer-Policy"] = "no-referrer"
        return response
    from archivebox.domains.export_service import export_jobs, launch_export

    if request.method == "POST":
        from archivebox.api.auth import token_from_request

        if not public_only and not token_from_request(request):
            from django.middleware.csrf import CsrfViewMiddleware

            rejected = CsrfViewMiddleware(lambda request: HttpResponse()).process_view(request, snapshot_export_view, (), {})
            if rejected:
                return rejected
        directory = request.POST.get("directory") if not public_only else None
        try:
            process = launch_export(
                query=query.urlencode(),
                user=user if user.is_authenticated else None,
                public_only=public_only,
                directory=directory or str(CONSTANTS.DATA_DIR / "exports"),
                format=format,
                max_bytes=MAX_ARCHIVE_BYTES if format in {"html_zip", "wacz"} else None,
            )
        except (ValueError, OSError) as error:
            return HttpResponseBadRequest(str(error))
        process.export_report = {"destination": process.cmd[process.cmd.index("--destination") + 1], "format": format}
        return JsonResponse(_job_data(process, api=api), status=202)
    jobs = export_jobs(query=query.urlencode(), user=user if user.is_authenticated else None, public_only=public_only)
    return JsonResponse(
        {"format": format, "query": query.urlencode(), "count": snapshots.count(), "jobs": [_job_data(job, api=api) for job in jobs]},
    )


@never_cache
def snapshot_export_job_view(request, process_id, *, action="status", api=False):
    if not apps.is_installed("archivebox.domains"):
        return HttpResponse(status=404)
    from archivebox.domains.export_service import export_jobs, export_log_prefix
    from archivebox.machine.models import Process

    try:
        process = get_object_or_404(Process, pk=process_id, worker_type="site-export")
    except (Http404, ValidationError, ValueError):
        return HttpResponse(status=404)
    args = process.cmd

    def value(name, default=""):
        return args[args.index(name) + 1] if name in args else default

    query = value("--query")
    public_only = "--public-only" in args
    user, error = _principal(request, session_authorized=not public_only)
    if error is not None:
        return error
    if not public_only and (not user.is_authenticated or str(user.pk) != value("--user")):
        return HttpResponse(status=403)
    principal = user if not public_only else None
    if not process.pwd.startswith(export_log_prefix(query=query, user=principal, public_only=public_only)):
        return HttpResponse(status=404)
    jobs = export_jobs(query=query, user=principal, public_only=public_only, process_id=process.pk)
    process = next((job for job in jobs if job.pk == process.pk), None)
    if process is None:
        return HttpResponse(status=404)
    if action == "cancel":
        if request.method != "POST":
            from django.http import HttpResponseNotAllowed

            return HttpResponseNotAllowed(["POST"])
        if public_only:
            return HttpResponse(status=403)
        from archivebox.api.auth import token_from_request

        if not token_from_request(request):
            from django.middleware.csrf import CsrfViewMiddleware

            rejected = CsrfViewMiddleware(lambda request: HttpResponse()).process_view(request, snapshot_export_job_view, (), {})
            if rejected:
                return rejected
        process.kill()
        return JsonResponse(_job_data(process, api=api))
    if request.method not in {"GET", "HEAD"}:
        from django.http import HttpResponseNotAllowed

        return HttpResponseNotAllowed(["GET", "HEAD"])
    if action == "download":
        if process.status != Process.StatusChoices.EXITED or process.exit_code != 0:
            return HttpResponse("Export is not complete.", status=409)
        if public_only:
            snapshots = get_export_queryset(query, public_only=True, config=getattr(request, "archivebox_config", None))
            cutoff = parse_datetime(value("--before"))
            if cutoff is None:
                return HttpResponse(status=404)
            snapshots = snapshots.filter(created_at__lte=cutoff)
            if process.export_report.get("selection_digest") != selection_digest(snapshots):
                return HttpResponse("The public selection changed. Export it again.", status=409)
        destination = Path(value("--destination"))
        if value("--format") not in {"html_zip", "wacz"}:
            return HttpResponse(status=404)
        filename = "site.zip" if value("--format") == "html_zip" else "site.wacz"
        file = destination / filename
        if not file.is_file() or file.is_symlink() or file.stat().st_size > MAX_ARCHIVE_BYTES:
            return HttpResponse(status=404)
        return FileResponse(file.open("rb"), as_attachment=True, filename=filename)
    return JsonResponse(_job_data(process, api=api))
