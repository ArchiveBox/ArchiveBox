"""Derived snapshot exports shared by library views, API requests and the CLI."""

import csv
import hashlib
import json
import logging
from copy import copy
from pathlib import Path

from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.apps import apps
from django.utils.dateparse import parse_datetime
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache

EXPORT_FORMATS = {"rss": "RSS", "csv": "CSV", "jsonl": "JSONL", "html_zip": "Static HTML ZIP", "wacz": "Unified WACZ"}
ALL_EXPORT_FORMATS = {**EXPORT_FORMATS, "html": "Static HTML to Disk"}
ARCHIVE_FORMATS = {"html_zip", "wacz", "html"}
MAX_ARCHIVE_BYTES = 4 * 1024**3
EXPORT_FIELDS = (
    "type",
    "schema_version",
    "id",
    "crawl_id",
    "folder_id",
    "folder_name",
    "created_by_id",
    "created_by_username",
    "persona_id",
    "persona_name",
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
    "public_only",
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


def get_export_queryset(query, *, user=None, public_only=True, config=None, request=None):
    from django.contrib.admin.utils import build_q_object_from_lookup_parameters, prepare_lookup_value
    from django.core.exceptions import FieldDoesNotExist, FieldError
    from django.db.models import Count
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.core.permissions import public_snapshots_queryset
    from archivebox.search.query import apply_snapshot_filters, apply_snapshot_search

    params = normalize_export_query(query)
    for api_name, view_name in (("folder_id", "folder"), ("search", "q"), ("status", "snapshot_status")):
        if api_name in params:
            if view_name in params and params.getlist(view_name) != params.getlist(api_name):
                raise ValueError(f"Conflicting {api_name} and {view_name} filters.")
            params.setlist(view_name, params.pop(api_name))
    allowed = {
        "q",
        "search_mode",
        "o",
        "id__in",
        "id__exact",
        "crawl__id__exact",
        "crawl_id__exact",
        "crawl_id",
        "folder_id",
        "folder_name",
        "created_by_id",
        "created_by_username",
        "persona_id",
        "persona_name",
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
    } | {"domain", "folder", "permissions", "snapshot_status", "archiveresult_status", "archive_state", "size", "tag"}
    if public_only and set(params) - allowed:
        raise ValueError("Invalid public snapshot filters.")
    queryset = Snapshot.objects.all()
    if public_only:
        queryset = public_snapshots_queryset(queryset)
    # Selection stays lazy: constructing an export must not fetch admin pages,
    # run counts, or load list-card manifests before the writer consumes it.
    try:
        queryset = apply_snapshot_filters(
            queryset,
            domain=params.get("domain"),
            folder_id=params.get("folder"),
            status=params.get("snapshot_status")
            if params.get("snapshot_status") in dict(Snapshot._meta.get_field("status").choices)
            else None,
            archive_state=params.get("archive_state"),
            size=params.get("size"),
            archiveresult_status=params.get("archiveresult_status"),
        )
    except (ValueError, ValidationError):
        # Invalid named list filters historically selected no rows.
        return queryset.none()
    if tag := params.get("tag"):
        queryset = queryset.filter(tags__id=tag)
    if permissions := params.get("permissions"):
        queryset = queryset.filter(permissions=permissions)
    controls = {
        "q",
        "search_mode",
        "o",
        "domain",
        "folder",
        "permissions",
        "snapshot_status",
        "archive_state",
        "size",
        "archiveresult_status",
        "tag",
    }
    lookup_params = {}
    for key, values in params.lists():
        if key in controls:
            continue
        lookup = Snapshot.SERIALIZED_FIELDS.get(key, key)
        try:
            field = Snapshot._meta.get_field(lookup.split("__", 1)[0])
        except FieldDoesNotExist as error:
            raise ValueError(f"Invalid snapshot field: {key}") from error
        if field.is_relation and "__" in lookup:
            suffix = lookup.split("__", 1)[1]
            related_key = suffix.split("__", 1)[0]
            serialized = tuple(path for path in Snapshot.SERIALIZED_FIELDS.values() if "__" in path)
            # Related credential/config fields must not become selectable just
            # because a URL can express an arbitrary Django relation lookup.
            permitted = key in allowed or field.get_lookup(suffix) is not None or related_key in {"pk", field.related_model._meta.pk.name}
            for path in serialized:
                if lookup != path and not lookup.startswith(path + "__"):
                    continue
                model = Snapshot
                for part in path.split("__"):
                    terminal = model._meta.get_field(part)
                    model = terminal.related_model
                # Django permits relation traversal through FK attnames too.
                # An exported ID supports its scalar lookups, never user secrets.
                terminal = terminal.target_field if terminal.is_relation else terminal
                suffix = lookup[len(path) :].removeprefix("__")
                permitted = permitted or not suffix or terminal.get_lookup(suffix) is not None
            if not permitted:
                raise ValueError(f"Invalid related snapshot field: {key}")
        lookup_params[lookup] = [prepare_lookup_value(lookup, value) for value in values]
    try:
        queryset = queryset.filter(build_q_object_from_lookup_parameters(lookup_params))
    except (FieldError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("Invalid snapshot filters.") from error
    ordering = list(queryset.query.order_by or ("-created_at",))
    if params.get("o"):
        from django.db.models.expressions import OrderBy
        from archivebox.core.admin_site import archivebox_admin

        # Numeric o is an admin URL convention. Read its existing column metadata
        # only at this boundary; the query/search implementation is UI-independent.
        model_admin = archivebox_admin._registry[Snapshot]
        selected = copy(request) if request is not None else None
        if selected is not None:
            selected.GET = params
            selected.user = user or request.user
        columns = list(model_admin.get_list_display(selected))
        has_actions = (
            bool(model_admin.get_actions(selected))
            if selected is not None
            else bool(user and (user.has_perm("core.change_snapshot") or user.has_perm("core.delete_snapshot")))
        )
        if has_actions:
            columns.insert(0, "action_checkbox")
        ordering = []
        for value in params["o"].split("."):
            try:
                _, descending, index = value.rpartition("-")
                name = columns[int(index)]
            except (IndexError, ValueError):
                continue
            attr = getattr(model_admin, name, None) or getattr(Snapshot, name, None)
            order_field = getattr(attr, "admin_order_field", None)
            if not order_field:
                try:
                    order_field = Snapshot._meta.get_field(name).name
                except FieldDoesNotExist:
                    continue
            if isinstance(order_field, OrderBy):
                order_field = order_field.copy()
                if descending:
                    order_field.reverse_ordering()
            elif hasattr(order_field, "resolve_expression"):
                order_field = order_field.desc() if descending else order_field.asc()
            else:
                order_field = order_field.removeprefix("-") if descending and order_field.startswith("-") else descending + order_field
            ordering.append(order_field)
        ordering.extend(queryset.query.order_by)
    if any(isinstance(field, str) and field.lstrip("-") == "ar_succeeded_count" for field in ordering):
        queryset = queryset.annotate(ar_succeeded_count=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED))
    if any(isinstance(field, str) and field.lstrip("-") == "tag_count" for field in ordering):
        queryset = queryset.annotate(tag_count=Count("tags", distinct=True))
    queryset = queryset.order_by(*ordering)
    if not queryset.totally_ordered:
        queryset = queryset.order_by(*ordering, "-pk")
    if params.get("q"):
        queryset = apply_snapshot_search(queryset, params["q"], search_mode=params.get("search_mode"), config=config)
    return queryset.distinct()


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
        public_only = request.GET.get("public_only") == "1"
        request = copy(request)
        request.GET = normalize_export_query(request.GET)
        if public_only:
            request.GET["public_only"] = "1"
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
        session_authorized=session_authorized
        or (not api and request.user.is_authenticated)
        or (request.method == "POST" and request.POST.get("session") == "1"),
    )
    if error is not None:
        return error
    public_only = not user.is_authenticated or request.GET.get("public_only") == "1"
    if public_only and format == "html":
        return HttpResponse(status=403)
    query = normalize_export_query(request.GET)
    try:
        snapshots = get_export_queryset(
            query,
            user=user,
            public_only=public_only,
            config=getattr(request, "archivebox_config", None),
            request=request,
        )
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
        if directory and not Path(directory).is_absolute():
            return HttpResponseBadRequest("Enter an absolute server directory path.")
        try:
            process = launch_export(
                query=query.urlencode(),
                user=user if user.is_authenticated else None,
                public_only=public_only,
                directory=directory or str(CONSTANTS.DATA_DIR / "exports"),
                format=format,
                max_bytes=MAX_ARCHIVE_BYTES if format in {"html_zip", "wacz"} else None,
            )
        except (ValueError, OSError):
            logging.getLogger(__name__).exception("Unable to start snapshot export")
            return HttpResponseBadRequest("Unable to start export.")
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


def model_export_response(records, format, *, name):
    """Authenticated model tables share CLI serialization and relationship columns."""
    from archivebox.misc.jsonl import write_record_table

    content_types = {"csv": "text/csv", "tsv": "text/tab-separated-values", "jsonl": "application/x-ndjson", "json": "application/json"}
    if format not in content_types:
        return HttpResponseBadRequest("Choose json, jsonl, csv, or tsv.")
    response = HttpResponse(content_type=content_types[format] + "; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}.{format}"'
    response["Cache-Control"] = "no-store"
    write_record_table(records, format=format, stream=response)
    return response
