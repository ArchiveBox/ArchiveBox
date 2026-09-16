import asyncio
import html
import io
import json
import mimetypes
import os
import posixpath
import re
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from functools import partial
from urllib.parse import urlencode

from abx_plugins.plugins.archivewebpage import replay_preview as archivewebpage_replay
from django.contrib.staticfiles import finders
from django.core.handlers.asgi import ASGIRequest
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.template import TemplateDoesNotExist, loader
from django.utils._os import safe_join
from django.utils.http import http_date
from django.utils.translation import gettext as _
from django.views import static

from archivebox.config.common import get_config
from archivebox.misc import replay_preview
from archivebox.misc.logging_util import printable_filesize

_HASHES_CACHE: dict[Path, tuple[float, dict[str, str]]] = {}


def _load_hash_map(snapshot_dir: Path) -> dict[str, str] | None:
    hashes_path = snapshot_dir / "hashes" / "hashes.json"
    if not hashes_path.exists():
        return None
    try:
        mtime = hashes_path.stat().st_mtime
    except OSError:
        return None

    cached = _HASHES_CACHE.get(hashes_path)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        data = json.loads(hashes_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None

    file_map = {str(entry.get("path")): entry.get("hash") for entry in data.get("files", []) if entry.get("path")}
    _HASHES_CACHE[hashes_path] = (mtime, file_map)
    return file_map


def _hash_for_path(document_root: Path, rel_path: str) -> str | None:
    file_map = _load_hash_map(document_root)
    if not file_map:
        return None
    return file_map.get(rel_path)


def _resolve_archive_path(document_root: str | Path, rel_path: str) -> tuple[Path, str]:
    rel_path = posixpath.normpath(rel_path).lstrip("/") if rel_path else ""
    fullpath = Path(safe_join(document_root, rel_path))
    if os.access(fullpath, os.R_OK):
        return fullpath, rel_path

    root = Path(document_root)
    current = root
    resolved_parts: list[str] = []
    for part in Path(rel_path).parts:
        exact = current / part
        if os.access(exact, os.R_OK):
            current = exact
            resolved_parts.append(part)
            continue

        folded_part = part.casefold()
        try:
            match = next((child for child in current.iterdir() if child.name.casefold() == folded_part), None)
        except OSError:
            match = None
        if match is None:
            return fullpath, rel_path

        current = match
        resolved_parts.append(match.name)

    return current, posixpath.join(*resolved_parts) if resolved_parts else ""


def _cache_policy(config=None, **config_kwargs) -> str:
    config = config or get_config(resolve_plugins=False, **config_kwargs)
    return "private" if config.PERMISSIONS == "private" else "public"


def _format_direntry_timestamp(stat_result: os.stat_result) -> str:
    timestamp = stat_result.st_birthtime if sys.platform == "darwin" else stat_result.st_mtime
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M")


def _safe_zip_stem(name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("._-")
    return safe_name or "archivebox"


class _ZipBuffer(io.RawIOBase):
    """A non-seekable ZIP destination drained after each source block."""

    def __init__(self):
        self.pending = bytearray()
        self.position = 0

    def write(self, data):
        self.pending.extend(data)
        self.position += len(data)
        return len(data)

    def tell(self):
        return self.position

    def drain(self):
        if self.pending:
            yield bytes(self.pending)
            self.pending.clear()


def _iter_visible_files(root: Path):
    """Yield non-hidden files in a stable order so ZIP output is deterministic."""

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirname for dirname in dirnames if not dirname.startswith("."))
        for filename in sorted(name for name in filenames if not name.startswith(".")):
            yield Path(current_root) / filename


def _iter_directory_zip(fullpath: Path, root_name: str):
    # Reading a block and yielding its compressed bytes in the same iterator
    # provides backpressure and closes all files when a download disconnects.
    with _ZipBuffer() as buffer:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for entry in _iter_visible_files(fullpath):
                info = zipfile.ZipInfo.from_file(entry, (Path(root_name) / entry.relative_to(fullpath)).as_posix())
                info.compress_type = archive.compression
                info.compress_level = archive.compresslevel
                with entry.open("rb") as source, archive.open(info, "w") as destination:
                    while chunk := source.read(64 * 1024):
                        destination.write(chunk)
                        yield from buffer.drain()
                yield from buffer.drain()
        yield from buffer.drain()


async def _stream_async(stream):
    # Django ASGI buffers synchronous iterators. Advance off the event loop,
    # waiting for an in-flight read before closing its iterator on cancellation.
    iterator = iter(stream)
    try:
        while True:
            read = asyncio.create_task(asyncio.to_thread(next, iterator, None))
            try:
                chunk = await asyncio.shield(read)
            except asyncio.CancelledError:
                await read
                raise
            if chunk is None:
                break
            yield chunk
    finally:
        iterator.close()


def _build_directory_zip_response(
    fullpath: Path,
    path: str,
    *,
    is_archive_replay: bool,
    use_async_stream: bool,
    config=None,
) -> StreamingHttpResponse:
    root_name = _safe_zip_stem(fullpath.name or Path(path).name or "archivebox")
    stream = _iter_directory_zip(fullpath, root_name)

    response = StreamingHttpResponse(stream, content_type="application/zip")
    if use_async_stream:
        response.streaming_content = _stream_async(stream)
    response.headers["Content-Disposition"] = f'attachment; filename="{root_name}.zip"'
    response.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=60, stale-while-revalidate=300"
    response.headers["Last-Modified"] = http_date(fullpath.stat().st_mtime)
    response.headers["X-Accel-Buffering"] = "no"
    return _apply_archive_replay_headers(
        response,
        fullpath=fullpath,
        content_type="application/zip",
        is_archive_replay=is_archive_replay,
        config=config,
    )


def _render_directory_index(request, path: str, fullpath: Path) -> HttpResponse:
    try:
        template = loader.select_template(
            [
                "static/directory_index.html",
                "static/directory_index",
            ],
        )
    except TemplateDoesNotExist:
        return static.directory_index(path, fullpath)

    entries = []
    file_list = []
    visible_entries = sorted(
        (entry for entry in fullpath.iterdir() if not entry.name.startswith(".")),
        key=lambda entry: (not entry.is_dir(), entry.name.lower()),
    )
    for entry in visible_entries:
        url = str(entry.relative_to(fullpath))
        if entry.is_dir():
            url += "/"
        file_list.append(url)

        stat_result = entry.stat()
        entries.append(
            {
                "name": url,
                "url": url,
                "is_dir": entry.is_dir(),
                "size": "—" if entry.is_dir() else printable_filesize(stat_result.st_size),
                "timestamp": _format_direntry_timestamp(stat_result),
            },
        )

    zip_query = request.GET.copy()
    zip_query["download"] = "zip"
    zip_url = request.path
    if zip_query:
        zip_url = f"{zip_url}?{zip_query.urlencode()}"

    directory_query = "?files=1" if request.GET.get("files") else ""
    path_suffix = f"{path.strip('/')}/" if path.strip("/") else ""
    snapshot_page_url = request.path
    if path_suffix and snapshot_page_url.endswith(path_suffix):
        snapshot_page_url = snapshot_page_url[: -len(path_suffix)]

    context = {
        "directory": f"{path}/",
        "file_list": file_list,
        "entries": entries,
        "zip_url": zip_url,
        "directory_query": directory_query,
        "snapshot_page_url": snapshot_page_url,
    }
    return HttpResponse(template.render(context))


# Ensure common web types are mapped consistently across platforms.
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/html", ".htm")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/x-ndjson", ".jsonl")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/yaml", ".yml")
mimetypes.add_type("text/yaml", ".yaml")
mimetypes.add_type("text/csv", ".csv")
mimetypes.add_type("text/tab-separated-values", ".tsv")
mimetypes.add_type("application/xml", ".xml")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("multipart/related", ".mhtml")
mimetypes.add_type("multipart/related", ".mht")

RISKY_REPLAY_MIMETYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}
RISKY_REPLAY_EXTENSIONS = {".html", ".htm", ".xhtml", ".svg", ".svgz"}
RISKY_REPLAY_MARKERS = (
    "<!doctype html",
    "<html",
    "<svg",
)


def _set_transformed_response_headers(response, fullpath: Path, statobj: os.stat_result, encoding: str | None, config) -> None:
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    response.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=60, stale-while-revalidate=300"
    response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
    if encoding:
        response.headers["Content-Encoding"] = encoding


def _content_type_base(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _is_risky_replay_document(fullpath: Path, content_type: str) -> bool:
    if fullpath.suffix.lower() in RISKY_REPLAY_EXTENSIONS:
        return True

    if _content_type_base(content_type) in RISKY_REPLAY_MIMETYPES:
        return True

    # Unknown archived response paths often have no extension. Sniff a small prefix
    # so one-domain no-JS mode still catches HTML/SVG documents.
    try:
        head = fullpath.read_bytes()[:4096].decode("utf-8", errors="ignore").lower()
    except (OSError, UnicodeDecodeError):
        return False

    return any(marker in head for marker in RISKY_REPLAY_MARKERS)


def _apply_archive_replay_headers(
    response: HttpResponse,
    *,
    fullpath: Path,
    content_type: str,
    is_archive_replay: bool,
    config=None,
    **config_kwargs,
) -> HttpResponse:
    if not is_archive_replay:
        return response

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    config = config or get_config(resolve_plugins=False, **config_kwargs)
    response.headers.setdefault("X-ArchiveBox-Security-Mode", config.SERVER_SECURITY_MODE)

    is_risky_replay = _is_risky_replay_document(fullpath, content_type)

    if config.SHOULD_NEUTER_RISKY_REPLAY and is_risky_replay and "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "sandbox; "
            "default-src 'self' data: blob:; "
            "script-src 'none'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "connect-src 'none'; "
            "worker-src 'none'; "
            "frame-ancestors 'self'; "
            "style-src 'self' 'unsafe-inline' data: blob:; "
            "img-src 'self' data: blob:; "
            "media-src 'self' data: blob:; "
            "font-src 'self' data: blob:;"
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")

    return response


def _is_asgi_request(request) -> bool:
    return isinstance(request, ASGIRequest) or "scope" in request.__dict__


def serve_static_with_byterange_support(request, path, document_root=None, show_indexes=False, is_archive_replay: bool = False):
    """
    Overrides Django's built-in django.views.static.serve function to support byte range requests.
    This allows you to do things like seek into the middle of a huge mp4 or WACZ without downloading the whole file.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """
    assert document_root
    config = request.__dict__.get("archivebox_config")
    if config is None:
        config = get_config(resolve_plugins=False)
    fullpath, path = _resolve_archive_path(document_root, path)
    replay_response = partial(_apply_archive_replay_headers, fullpath=fullpath, is_archive_replay=is_archive_replay, config=config)
    if os.access(fullpath, os.R_OK) and fullpath.is_dir():
        if request.GET.get("download") == "zip" and show_indexes:
            return _build_directory_zip_response(
                fullpath,
                path,
                is_archive_replay=is_archive_replay,
                use_async_stream=_is_asgi_request(request),
                config=config,
            )
        if show_indexes:
            response = _render_directory_index(request, path, fullpath)
            response.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=60, stale-while-revalidate=300"
            response.headers["Last-Modified"] = http_date(fullpath.stat().st_mtime)
            return replay_response(response, content_type="text/html")
        raise Http404(_("Directory indexes are not allowed here."))
    if not os.access(fullpath, os.R_OK):
        raise Http404(_("“%(path)s” does not exist") % {"path": fullpath})

    statobj = fullpath.stat()
    document_root = Path(document_root) if document_root else None
    rel_path = path
    etag = None
    if document_root:
        file_hash = _hash_for_path(document_root, rel_path)
        if file_hash:
            etag = f'"{file_hash}"'

    if etag:
        inm = request.META.get("HTTP_IF_NONE_MATCH")
        if inm:
            inm_list = [item.strip() for item in inm.split(",")]
            if etag in inm_list or etag.strip('"') in [i.strip('"') for i in inm_list]:
                not_modified = HttpResponseNotModified()
                not_modified.headers["ETag"] = etag
                not_modified.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=31536000, immutable"
                not_modified.headers["Last-Modified"] = http_date(statobj.st_mtime)
                return replay_response(not_modified, content_type="")

    content_type, encoding = mimetypes.guess_type(str(fullpath))
    preserve_plain_text = fullpath.suffix.lower() in {".log", ".sh"}
    if preserve_plain_text:
        content_type = "text/plain"
    content_type = content_type or "application/octet-stream"
    # Add charset for text-like types (best guess), but don't override the type.
    is_text_like = content_type.startswith("text/") or content_type in {
        "application/json",
        "application/javascript",
        "application/xml",
        "application/x-ndjson",
        "image/svg+xml",
    }
    if is_text_like and "charset=" not in content_type:
        content_type = f"{content_type}; charset=utf-8"
    preview_as_text_html = (
        bool(request.GET.get("preview"))
        and is_text_like
        and not content_type.startswith("text/html")
        and not content_type.startswith("image/svg+xml")
    )
    preview_as_image_html = (
        bool(request.GET.get("preview")) and content_type.startswith("image/") and not content_type.startswith("image/svg+xml")
    )
    preview_as_archivewebpage_html = bool(request.GET.get("preview")) and archivewebpage_replay.is_replay_target(fullpath.name)

    # Respect the If-Modified-Since header for non-markdown responses.
    if not content_type.startswith(("text/plain", "text/html")) and not static.was_modified_since(
        request.META.get("HTTP_IF_MODIFIED_SINCE"),
        statobj.st_mtime,
    ):
        return replay_response(HttpResponseNotModified(), content_type=content_type)

    def transformed_response(body: str, response_type: str):
        response = HttpResponse(body, content_type=response_type)
        _set_transformed_response_headers(response, fullpath, statobj, encoding, config)
        return replay_response(response, content_type=response_type)

    # Wrap text-like outputs in HTML when explicitly requested for iframe previewing.
    if preview_as_text_html:
        try:
            max_preview_size = 10 * 1024 * 1024
            if statobj.st_size <= max_preview_size:
                decoded = fullpath.read_text(encoding="utf-8", errors="replace")
                wrapped = replay_preview._render_text_preview_document(decoded, fullpath.name)
                return transformed_response(wrapped, "text/html; charset=utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            preview_as_text_html = False

    if preview_as_image_html:
        try:
            preview_query = request.GET.copy()
            preview_query.pop("preview", None)
            raw_image_url = request.path
            if preview_query:
                raw_image_url = f"{raw_image_url}?{urlencode(list(preview_query.lists()), doseq=True)}"
            wrapped = replay_preview._render_image_preview_document(raw_image_url, fullpath.name)
            return transformed_response(wrapped, "text/html; charset=utf-8")
        except (OSError, ValueError):
            preview_as_image_html = False

    if preview_as_archivewebpage_html:
        try:
            raw_query = request.GET.copy()
            raw_query.pop("preview", None)
            raw_output_path = request.path
            if raw_query:
                raw_output_path = f"{raw_output_path}?{raw_query.urlencode()}"
            body, preview_content_type, headers = archivewebpage_replay.render_preview_response(
                fullpath.name,
                raw_output_path,
                wacz_path=fullpath,
                fallback_url=request.archivebox_snapshot_url or "",
                last_modified=http_date(statobj.st_mtime),
                etag=etag or "",
                cache_control=(
                    f"{_cache_policy(config=config)}, max-age=31536000, immutable"
                    if etag
                    else f"{_cache_policy(config=config)}, max-age=60, stale-while-revalidate=300"
                ),
                content_encoding=encoding or "",
            )
            response = HttpResponse(body, content_type=preview_content_type)
            for key, value in headers.items():
                response.headers[key] = value
            return replay_response(response, content_type=preview_content_type)
        except (OSError, RuntimeError, ValueError):
            preview_as_archivewebpage_html = False

    # Heuristic fix: some archived HTML outputs are stored with HTML-escaped markup
    # or markdown sources. If so, render sensibly.
    if not preserve_plain_text and content_type.startswith(("text/plain", "text/html")):
        try:
            max_unescape_size = 10 * 1024 * 1024  # 10MB cap to avoid heavy memory use
            if statobj.st_size <= max_unescape_size:
                raw = fullpath.read_bytes()
                decoded = raw.decode("utf-8", errors="replace")
                escaped_count = decoded.count("&lt;") + decoded.count("&gt;")
                tag_count = decoded.count("<")
                if escaped_count and escaped_count > tag_count * 2:
                    decoded = html.unescape(decoded)
                rewritten_html, rewritten_count = ("", 0)
                if content_type.startswith("text/html") and document_root:
                    rewritten_html, rewritten_count = replay_preview._rewrite_html_image_sources_for_request(
                        request,
                        decoded,
                        document_root,
                        rel_path,
                    )
                markdown_candidate = replay_preview._extract_markdown_candidate(decoded)
                if replay_preview._looks_like_markdown(markdown_candidate):
                    wrapped = replay_preview._render_markdown_document(markdown_candidate)
                    wrapped, _rewrite_count = replay_preview._rewrite_html_image_sources_for_request(
                        request,
                        wrapped,
                        document_root,
                        rel_path,
                    )
                    wrapped = replay_preview._apply_transformed_html_preview_style(wrapped)
                    return transformed_response(wrapped, "text/html; charset=utf-8")
                if rewritten_count:
                    rewritten_html = replay_preview._apply_transformed_html_preview_style(rewritten_html)
                    return transformed_response(rewritten_html, content_type)
                if escaped_count and escaped_count > tag_count * 2:
                    decoded = replay_preview._apply_transformed_html_preview_style(decoded)
                    return transformed_response(decoded, content_type)
        except (OSError, UnicodeDecodeError, ValueError):
            pass

    # setup response object
    ranged_file = RangedFileReader(fullpath.open("rb"))
    response = StreamingHttpResponse(ranged_file, content_type=content_type)
    if _is_asgi_request(request):
        response.streaming_content = _stream_async(ranged_file)
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    if etag:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = f"{_cache_policy(config=config)}, max-age=60, stale-while-revalidate=300"
    if is_text_like:
        response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
    if content_type.startswith("image/"):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"

    # handle byte-range requests by serving chunk of file
    if stat.S_ISREG(statobj.st_mode):
        size = statobj.st_size
        response["Content-Length"] = size
        response["Accept-Ranges"] = "bytes"
        response["X-Django-Ranges-Supported"] = "1"
        # Respect the Range header.
        if "HTTP_RANGE" in request.META:
            try:
                ranges = parse_range_header(request.META["HTTP_RANGE"], size)
            except ValueError:
                ranges = None
            # only handle syntactically valid headers, that are simple (no
            # multipart byteranges)
            if ranges is not None and len(ranges) == 1:
                start, stop = ranges[0]
                if stop > size:
                    # requested range not satisfiable
                    return HttpResponse(status=416)
                ranged_file.start = start
                ranged_file.stop = stop
                response["Content-Range"] = f"bytes {start}-{stop - 1}/{size}"
                response["Content-Length"] = stop - start
                response.status_code = 206
    if encoding:
        response.headers["Content-Encoding"] = encoding
    return replay_response(response, content_type=content_type)


def serve_static(request, path, **kwargs):
    """
    Serve static files below a given point in the directory structure or
    from locations inferred from the staticfiles finders.

    To use, put a URL pattern such as::

        from django.contrib.staticfiles import views

        path('<path:path>', views.serve)

    in your URLconf.

    It uses the django.views.static.serve() view to serve the found files.
    """

    normalized_path = posixpath.normpath(path).lstrip("/")
    absolute_path = finders.find(normalized_path)
    if not absolute_path:
        if path.endswith("/") or path == "":
            raise Http404("Directory indexes are not allowed here.")
        raise Http404(f"'{path}' could not be found")
    document_root, path = os.path.split(absolute_path)
    return serve_static_with_byterange_support(request, path, document_root=document_root, **kwargs)


def parse_range_header(header, resource_size):
    """
    Parses a range header into a list of two-tuples (start, stop) where `start`
    is the starting byte of the range (inclusive) and `stop` is the ending byte
    position of the range (exclusive).
    Returns None if the value of the header is not syntactically valid.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """
    if not header or "=" not in header:
        return None

    ranges = []
    units, range_ = header.split("=", 1)
    units = units.strip().lower()

    if units != "bytes":
        return None

    for val in range_.split(","):
        val = val.strip()
        if "-" not in val:
            return None

        if val.startswith("-"):
            # suffix-byte-range-spec: this form specifies the last N bytes of an
            # entity-body
            start = resource_size + int(val)
            start = max(start, 0)
            stop = resource_size
        else:
            # byte-range-spec: first-byte-pos "-" [last-byte-pos]
            start, stop = val.split("-", 1)
            start = int(start)
            # the +1 is here since we want the stopping point to be exclusive, whereas in
            # the HTTP spec, the last-byte-pos is inclusive
            stop = int(stop) + 1 if stop else resource_size
            if start >= stop:
                return None

        ranges.append((start, stop))

    return ranges


class RangedFileReader:
    """
    Wraps a file like object with an iterator that runs over part (or all) of
    the file defined by start and stop. Blocks of block_size will be returned
    from the starting position, up to, but not including the stop point.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """

    block_size = 8192

    def __init__(self, file_like, start=0, stop=float("inf"), block_size=None):
        self.f = file_like
        self.block_size = block_size or RangedFileReader.block_size
        self.start = start
        self.stop = stop

    def __iter__(self):
        try:
            self.f.seek(self.start)
            position = self.start
            while position < self.stop:
                data = self.f.read(min(self.block_size, self.stop - position))
                if not data:
                    break

                yield data
                position += len(data)
        finally:
            self.close()

    def close(self):
        self.f.close()
