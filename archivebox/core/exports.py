"""Derived snapshot exports shared by library views, API requests and the CLI."""

import csv
import hashlib
import json
import logging
from asyncio import to_thread
from copy import copy
from pathlib import Path
from tempfile import TemporaryFile

from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.db.models import Prefetch
from django.apps import apps
from django.utils.dateparse import parse_datetime
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache

from archivebox.misc.serve_static import RangedFileReader, _is_asgi_request, _stream_ranged_file_async

EXPORT_FORMATS = {"rss": "RSS", "csv": "CSV", "jsonl": "JSONL", "html_zip": "Static HTML ZIP", "wacz": "Unified WACZ"}
ALL_EXPORT_FORMATS = {**EXPORT_FORMATS, "html": "Static HTML to Disk"}
METADATA_FORMATS = {"csv", "jsonl", "rss", "txt"}
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
    "sidebar",
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


def snapshot_admin_sort(value, request=None, user=None):
    """Resolve Django's numeric changelist columns to stable snapshot fields."""
    from django.core.exceptions import FieldDoesNotExist
    from archivebox.core.admin_site import archivebox_admin
    from archivebox.core.models import Snapshot

    model_admin = archivebox_admin._registry[Snapshot]
    columns = list(model_admin.get_list_display(request))
    has_actions = (
        bool(model_admin.get_actions(request))
        if request is not None
        else bool(
            user and (user.has_perm("core.change_snapshot") or user.has_perm("core.delete_snapshot")),
        )
    )
    if has_actions:
        columns.insert(0, "action_checkbox")
    ordering = []
    for item in value.split("."):
        index = item.removeprefix("-")
        if not index.isascii() or not index.isdecimal() or len(index) > 4 or int(index) >= len(columns):
            continue
        name = columns[int(index)]
        attr = getattr(model_admin, name, None) or getattr(Snapshot, name, None)
        field = getattr(attr, "admin_order_field", None)
        if not field:
            try:
                field = Snapshot._meta.get_field(name).name
            except FieldDoesNotExist:
                continue
        if isinstance(field, str):
            descending = item.startswith("-") != field.startswith("-")
            ordering.append(("-" if descending else "") + field.lstrip("-"))
    return ordering


EXPORT_SORT_FIELDS = frozenset(
    {
        "id",
        "pk",
        "url",
        "title",
        "permissions",
        "created_at",
        "modified_at",
        "bookmarked_at",
        "downloaded_at",
        "timestamp",
        "status",
        "output_size",
        "tag_count",
        "ar_succeeded_count",
    },
)


def get_export_queryset(query, *, user=None, public_only=True, config=None, request=None, selection_before=None):
    from django.contrib.admin.utils import build_q_object_from_lookup_parameters, prepare_lookup_value
    from django.core.exceptions import FieldDoesNotExist, FieldError
    from django.db.models import Count, Subquery
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
        "sort",
        "max_results",
        "id__in",
        "id__exact",
        "crawl__id__exact",
        "crawl_id__exact",
        "crawl_id",
        "folder_id",
        "folder_name",
        "created_by_id",
        "created_by_username",
        "created_by_username__iexact",
        "persona_id",
        "persona_name",
        "url__regex",
        "site_scope",
        "domain_search",
        "url__startswith",
        "url__icontains",
        "crawl__created_by__id__exact",
        "crawl__created_by__isnull",
        "created_at__gte",
        "created_at__lt",
        "created_at__lte",
        "created_at__isnull",
        "bookmarked_at__lte",
        "downloaded_at__gte",
        "downloaded_at__lt",
        "downloaded_at__isnull",
    } | {"domain", "folder", "permissions", "snapshot_status", "archiveresult_status", "archive_state", "size", "tag"}
    if public_only and set(params) - allowed:
        raise ValueError("Invalid public snapshot filters.")
    queryset = Snapshot.objects.all()
    if selection_before is not None:
        queryset = queryset.filter(created_at__lte=selection_before)
    if public_only:
        queryset = public_snapshots_queryset(queryset)
    # Selection stays lazy: constructing an export must not fetch admin pages,
    # run counts, or load list-card manifests before the writer consumes it.
    try:
        queryset = apply_snapshot_filters(
            queryset,
            domain=params.get("domain"),
            site_scopes=params.getlist("site_scope"),
            domain_search=params.get("domain_search"),
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
        "sort",
        "max_results",
        "domain",
        "site_scope",
        "domain_search",
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
    if sort := params.get("sort"):
        fields = sort.split(",")
        if len(fields) > len(EXPORT_SORT_FIELDS) or any(field.removeprefix("-") not in EXPORT_SORT_FIELDS for field in fields):
            raise ValueError("Invalid snapshot sort.")
        ordering = fields
    elif params.get("o"):
        ordering = snapshot_admin_sort(params["o"], request=request, user=user) + list(queryset.query.order_by)
    if any(isinstance(field, str) and field.lstrip("-") == "ar_succeeded_count" for field in ordering):
        queryset = queryset.annotate(ar_succeeded_count=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED))
    if any(isinstance(field, str) and field.lstrip("-") == "tag_count" for field in ordering):
        queryset = queryset.annotate(tag_count=Count("tags", distinct=True))
    queryset = queryset.order_by(*ordering)
    if not queryset.totally_ordered:
        queryset = queryset.order_by(*ordering, "-pk")
    partial = False
    if params.get("q"):
        queryset = apply_snapshot_search(queryset, params["q"], search_mode=params.get("search_mode"), config=config, public=public_only)
        partial = getattr(queryset, "search_partial", False)
    queryset = queryset.distinct()
    if limit := params.get("max_results"):
        try:
            limit = int(limit)
        except ValueError as error:
            raise ValueError("Invalid snapshot export limit.") from error
        if limit <= 0:
            raise ValueError("Invalid snapshot export limit.")
        queryset = queryset.filter(pk__in=Subquery(queryset.values("pk")[:limit]))
    queryset.search_partial = partial
    return queryset


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
        from archivebox.api.v1_core import _snapshots_rss_response, _write_spooled_snapshots_rss

        web_export = request is not None
        if request is None:
            from archivebox.config.common import get_config
            from urllib.parse import urlsplit

            from io import BytesIO
            from django.core.handlers.wsgi import WSGIRequest

            origin = urlsplit(get_config().BASE_URL or "http://localhost:8000")
            request = WSGIRequest(
                {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/admin/core/snapshot/export.rss",
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
        # A crawl can hold megabytes of intake. Select only the fields needed
        # by RSS (including archive_path_from_db). Web exports prefetch tags
        # into lists so cached related QuerySets cannot retain completed batches.
        rss_snapshots = (
            snapshots.select_related("crawl__created_by")
            .prefetch_related(Prefetch("tags", to_attr="_rss_export_tags") if web_export else "tags")
            .only(
                "id",
                "url",
                "title",
                "timestamp",
                "bookmarked_at",
                "created_at",
                "modified_at",
                "fs_version",
                "crawl_id",
                "crawl__id",
                "crawl__created_by_id",
                "crawl__created_by__id",
                "crawl__created_by__username",
            )
        )
        rss_rows = rss_snapshots.iterator(chunk_size=100)
        if web_export:
            _write_spooled_snapshots_rss(request, snapshots=rss_rows, output=output)
        else:
            response = _snapshots_rss_response(request, snapshots=rss_rows)
            output.write(response.content.decode())
        return
    if format == "txt":
        for url in snapshots.values_list("url", flat=True).iterator(chunk_size=1000):
            output.write(url + "\n")
        return
    if format not in {"csv", "jsonl"}:
        raise ValueError("Select RSS, CSV, or JSONL.")
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS) if format == "csv" else None
    if writer:
        writer.writeheader()
    # Web exports drop these fields below; do not fetch or serialize them.
    for record in iter_snapshot_json(snapshots, include_private_fields=request is None):
        row = {field: record[field] for field in EXPORT_FIELDS}
        if writer:
            writer.writerow(row)
        else:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snapshot_metadata_file(request, snapshots, format):
    content_type = {
        "csv": "text/csv; charset=utf-8",
        "jsonl": "application/x-ndjson",
        "rss": "application/rss+xml; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
    }[format]
    filename = "" if format == "rss" else f"snapshots.{format}"
    return _spooled_export_response(
        request,
        lambda output: write_snapshot_metadata(snapshots, format, output, request=request),
        content_type=content_type,
        filename=filename,
    )


def _spooled_export_response(request, write, *, content_type, filename):
    # Keep the generated body off the Python heap and finish the database read
    # before sending headers. The anonymous tempfile is never a download path.
    spool = TemporaryFile()
    try:
        if own_stream := getattr(request, "scope", {}).get("archivebox.own_response_stream"):

            async def close_spool():
                await to_thread(spool.close)

            own_stream(close_spool)

        with open(spool.fileno(), "w", encoding="utf-8", newline="", closefd=False) as output:
            write(output)
        if request.method == "HEAD":
            response = HttpResponse(content_type=content_type, headers={"Content-Length": str(spool.tell())})
            if filename:
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
            spool.close()
            return response

        spool.seek(0)
        response = FileResponse(spool, content_type=content_type, as_attachment=bool(filename), filename=filename)
        if _is_asgi_request(request):
            # FileResponse retains the closer, but Django ASGI must not buffer
            # its default synchronous iterator into a list before sending it.
            response.streaming_content = _stream_ranged_file_async(RangedFileReader(spool))
        return response
    except BaseException:
        spool.close()
        raise


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
def snapshot_export_view(request, format, *, api=False):
    from archivebox.workers.request_activity import mark_request_family

    mark_request_family(request, "export")
    from archivebox.config import CONSTANTS

    if format not in METADATA_FORMATS and (format not in ARCHIVE_FORMATS or not apps.is_installed("archivebox.domains")):
        return HttpResponse(status=404)
    allowed_methods = ["GET", "HEAD", "POST"] if format in ARCHIVE_FORMATS else ["GET", "HEAD"]
    if request.method not in allowed_methods:
        from django.http import HttpResponseNotAllowed

        return HttpResponseNotAllowed(allowed_methods)
    user, error = _principal(
        request,
        session_authorized=(not api and request.user.is_authenticated) or (request.method == "POST" and request.POST.get("session") == "1"),
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
        response = _snapshot_metadata_file(request, snapshots, format)
        response["Referrer-Policy"] = "no-referrer"
        if getattr(snapshots, "search_partial", False):
            response["X-ArchiveBox-Search-Partial"] = "1"
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
    from archivebox.workers.request_activity import mark_request_family

    mark_request_family(request, "export")
    if not apps.is_installed("archivebox.domains"):
        return HttpResponse(status=404)
    from archivebox.domains.export_service import export_jobs, export_log_prefix
    from archivebox.machine.models import Process

    try:
        process = get_object_or_404(Process.objects.defer("stdout", "stderr"), pk=process_id, worker_type="site-export")
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
            cutoff = parse_datetime(value("--before"))
            if cutoff is None:
                return HttpResponse(status=404)
            snapshots = get_export_queryset(
                query,
                public_only=True,
                config=getattr(request, "archivebox_config", None),
                selection_before=cutoff,
            )
            if process.export_report.get("selection_digest") != selection_digest(snapshots):
                return HttpResponse("The public selection changed. Export it again.", status=409)
        destination = Path(value("--destination"))
        if value("--format") not in {"html_zip", "wacz"}:
            return HttpResponse(status=404)
        filename = "site.zip" if value("--format") == "html_zip" else "site.wacz"
        file = destination / filename
        if not file.is_file() or file.is_symlink() or file.stat().st_size > MAX_ARCHIVE_BYTES:
            return HttpResponse(status=404)
        stream = file.open("rb")
        response = FileResponse(stream, as_attachment=True, filename=filename)
        # Django otherwise buffers the synchronous file iterator under ASGI.
        if _is_asgi_request(request):
            response.streaming_content = _stream_ranged_file_async(RangedFileReader(stream))
        return response
    return JsonResponse(_job_data(process, api=api))


def model_export_response(request, records, format, *, name):
    """Authenticated model tables share CLI serialization and relationship columns."""
    from archivebox.misc.jsonl import write_record_table

    content_types = {"csv": "text/csv", "tsv": "text/tab-separated-values", "jsonl": "application/x-ndjson", "json": "application/json"}
    if format not in content_types:
        return HttpResponseBadRequest("Choose json, jsonl, csv, or tsv.")

    def write(output):
        if format != "json":
            write_record_table(records, format=format, stream=output)
            return
        # Keep the array and newline byte-identical to the former json.dump
        # of a list without collecting every rendered model in memory.
        encoder = json.JSONEncoder(ensure_ascii=False)
        output.write("[")
        for index, record in enumerate(records):
            if index:
                output.write(", ")
            output.write(encoder.encode(record))
        output.write("]\n")

    response = _spooled_export_response(
        request,
        write,
        content_type=content_types[format] + "; charset=utf-8",
        filename=f"{name}.{format}",
    )
    response["Cache-Control"] = "no-store"
    return response
