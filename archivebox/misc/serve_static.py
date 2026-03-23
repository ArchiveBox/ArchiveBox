import html
import json
import re
import os
import stat
import asyncio
import posixpath
import mimetypes
import importlib
import queue
import threading
import time
import zipfile
from datetime import datetime
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from django.contrib.staticfiles import finders
from django.template import TemplateDoesNotExist, loader
from django.views import static
from django.http import StreamingHttpResponse, Http404, HttpResponse, HttpResponseNotModified
from django.utils._os import safe_join
from django.utils.http import http_date
from django.utils.translation import gettext as _
from archivebox.config.common import SERVER_CONFIG
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
    except Exception:
        return None

    file_map = {str(entry.get("path")): entry.get("hash") for entry in data.get("files", []) if entry.get("path")}
    _HASHES_CACHE[hashes_path] = (mtime, file_map)
    return file_map


def _hash_for_path(document_root: Path, rel_path: str) -> str | None:
    file_map = _load_hash_map(document_root)
    if not file_map:
        return None
    return file_map.get(rel_path)


def _cache_policy() -> str:
    return "public" if SERVER_CONFIG.PUBLIC_SNAPSHOTS else "private"


def _format_direntry_timestamp(stat_result: os.stat_result) -> str:
    timestamp = getattr(stat_result, "st_birthtime", None) or stat_result.st_mtime
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _safe_zip_stem(name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("._-")
    return safe_name or "archivebox"


class _StreamingQueueWriter:
    """Expose a write-only file-like object so zipfile can stream into a queue."""

    def __init__(self, output_queue: queue.Queue[bytes | BaseException | object]) -> None:
        self.output_queue = output_queue
        self.position = 0

    def write(self, data: bytes) -> int:
        if data:
            self.output_queue.put(data)
            self.position += len(data)
        return len(data)

    def tell(self) -> int:
        return self.position

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def _iter_visible_files(root: Path):
    """Yield non-hidden files in a stable order so ZIP output is deterministic."""

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirname for dirname in dirnames if not dirname.startswith("."))
        for filename in sorted(name for name in filenames if not name.startswith(".")):
            yield Path(current_root) / filename


def _build_directory_zip_response(
    fullpath: Path,
    path: str,
    *,
    is_archive_replay: bool,
    use_async_stream: bool,
) -> StreamingHttpResponse:
    root_name = _safe_zip_stem(fullpath.name or Path(path).name or "archivebox")
    sentinel = object()
    output_queue: queue.Queue[bytes | BaseException | object] = queue.Queue(maxsize=8)
    initial_chunk_target = 64 * 1024
    initial_chunk_wait = 0.05

    def build_zip() -> None:
        # zipfile wants a write-only file object. Feed those bytes straight into
        # a queue so the response can stream them out as soon as they are ready.
        writer = _StreamingQueueWriter(output_queue)
        try:
            with zipfile.ZipFile(writer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
                for entry in _iter_visible_files(fullpath):
                    rel_parts = entry.relative_to(fullpath).parts
                    arcname = Path(root_name, *rel_parts).as_posix()
                    zip_file.write(entry, arcname)
        except BaseException as err:
            output_queue.put(err)
        finally:
            output_queue.put(sentinel)

    threading.Thread(target=build_zip, name=f"zip-stream-{root_name}", daemon=True).start()

    def iter_zip_chunks():
        # Emit a meaningful first chunk quickly so browsers show the download
        # immediately instead of waiting on dozens of tiny ZIP header writes.
        first_chunk = bytearray()
        initial_deadline = time.monotonic() + initial_chunk_wait

        while True:
            timeout = max(initial_deadline - time.monotonic(), 0) if len(first_chunk) < initial_chunk_target else None
            try:
                chunk = output_queue.get(timeout=timeout) if timeout is not None else output_queue.get()
            except queue.Empty:
                if first_chunk:
                    yield bytes(first_chunk)
                    first_chunk.clear()
                    continue
                chunk = output_queue.get()

            if chunk is sentinel:
                if first_chunk:
                    yield bytes(first_chunk)
                break
            if isinstance(chunk, BaseException):
                raise chunk
            if len(first_chunk) < initial_chunk_target:
                first_chunk.extend(chunk)
                if len(first_chunk) >= initial_chunk_target or time.monotonic() >= initial_deadline:
                    yield bytes(first_chunk)
                    first_chunk.clear()
                continue
            yield chunk

    async def stream_zip_async():
        # Django ASGI buffers sync StreamingHttpResponse iterators by consuming
        # them into a list. Drive the same sync iterator from a worker thread so
        # Daphne can send each chunk as it arrives instead of buffering the ZIP.
        iterator = iter(iter_zip_chunks())
        while True:
            chunk = await asyncio.to_thread(next, iterator, None)
            if chunk is None:
                break
            yield chunk

    response = StreamingHttpResponse(
        stream_zip_async() if use_async_stream else iter_zip_chunks(),
        content_type="application/zip",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{root_name}.zip"'
    response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
    response.headers["Last-Modified"] = http_date(fullpath.stat().st_mtime)
    response.headers["X-Accel-Buffering"] = "no"
    return _apply_archive_replay_headers(
        response,
        fullpath=fullpath,
        content_type="application/zip",
        is_archive_replay=is_archive_replay,
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

    context = {
        "directory": f"{path}/",
        "file_list": file_list,
        "entries": entries,
        "zip_url": zip_url,
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

try:
    _markdown = getattr(importlib.import_module("markdown"), "markdown")
except ImportError:
    _markdown: Callable[..., str] | None = None

MARKDOWN_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+(?:\([^)]*\)[^)\s]*)*)\)")
MARKDOWN_INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
MARKDOWN_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
HTML_TAG_RE = re.compile(r"<[A-Za-z][^>]*>")
HTML_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", flags=re.IGNORECASE | re.DOTALL)
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


def _extract_markdown_candidate(text: str) -> str:
    candidate = text
    body_match = HTML_BODY_RE.search(candidate)
    if body_match:
        candidate = body_match.group(1)
    candidate = re.sub(r"^\s*<p[^>]*>", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"</p>\s*$", "", candidate, flags=re.IGNORECASE)
    return candidate.strip()


def _looks_like_markdown(text: str) -> bool:
    lower = text.lower()
    if "<html" in lower and "<head" in lower and "</body>" in lower:
        return False
    md_markers = 0
    md_markers += len(re.findall(r"^\s{0,3}#{1,6}\s+\S", text, flags=re.MULTILINE))
    md_markers += len(re.findall(r"^\s*[-*+]\s+\S", text, flags=re.MULTILINE))
    md_markers += len(re.findall(r"^\s*\d+\.\s+\S", text, flags=re.MULTILINE))
    md_markers += text.count("[TOC]")
    md_markers += len(MARKDOWN_INLINE_LINK_RE.findall(text))
    md_markers += text.count("\n---") + text.count("\n***")
    return md_markers >= 6


def _render_text_preview_document(text: str, title: str) -> str:
    escaped_title = html.escape(title)
    escaped_text = html.escape(text)
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <style>
        :root {{
            color-scheme: dark;
        }}
        html, body {{
            margin: 0;
            padding: 0;
            background: #111;
            color: #f3f3f3;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        }}
        .archivebox-text-preview-header {{
            position: sticky;
            top: 0;
            z-index: 1;
            padding: 10px 14px;
            font-size: 12px;
            line-height: 1.4;
            color: #bbb;
            background: rgba(17, 17, 17, 0.96);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(8px);
        }}
        .archivebox-text-preview {{
            margin: 0;
            padding: 14px;
            white-space: pre-wrap;
            word-break: break-word;
            tab-size: 2;
            line-height: 1.45;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="archivebox-text-preview-header">{escaped_title}</div>
    <pre class="archivebox-text-preview">{escaped_text}</pre>
</body>
</html>"""


def _render_image_preview_document(image_url: str, title: str) -> str:
    escaped_title = html.escape(title)
    escaped_url = html.escape(image_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <style>
        :root {{
            color-scheme: dark;
        }}
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            min-height: 100%;
            background: #fff;
        }}
        body {{
            overflow: auto;
        }}
        .archivebox-image-preview {{
            width: 100%;
            min-width: 100%;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            box-sizing: border-box;
        }}
        .archivebox-image-preview img {{
            display: block;
            width: auto;
            max-width: 100%;
            height: auto;
            margin: 0 auto;
        }}
    </style>
</head>
<body>
    <div class="archivebox-image-preview">
        <img src="{escaped_url}" alt="{escaped_title}">
    </div>
</body>
</html>"""


def _render_markdown_fallback(text: str) -> str:
    if _markdown is not None and not HTML_TAG_RE.search(text):
        try:
            return _markdown(
                text,
                extensions=["extra", "toc", "sane_lists"],
                output_format="html",
            )
        except Exception:
            pass

    lines = text.splitlines()
    headings = []

    def slugify(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
        return slug or "section"

    for raw_line in lines:
        heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", raw_line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2).strip()
            headings.append((level, content, slugify(content)))

    html_lines = []
    in_code = False
    in_ul = False
    in_ol = False
    in_blockquote = False

    def render_inline(markup: str) -> str:
        content = MARKDOWN_INLINE_IMAGE_RE.sub(r'<img alt="\1" src="\2">', markup)
        content = MARKDOWN_INLINE_LINK_RE.sub(r'<a href="\2">\1</a>', content)
        content = MARKDOWN_BOLD_RE.sub(r"<strong>\1</strong>", content)
        content = MARKDOWN_ITALIC_RE.sub(r"<em>\1</em>", content)
        return content

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                html_lines.append("</code></pre>")
                in_code = False
            else:
                close_lists()
                if in_blockquote:
                    html_lines.append("</blockquote>")
                    in_blockquote = False
                html_lines.append("<pre><code>")
                in_code = True
            continue

        if in_code:
            html_lines.append(html.escape(line))
            continue

        if not stripped:
            close_lists()
            if in_blockquote:
                html_lines.append("</blockquote>")
                in_blockquote = False
            html_lines.append("<br/>")
            continue

        heading_match = re.match(r"^\s*((?:<[^>]+>\s*)*)(#{1,6})\s+(.*)$", line)
        if heading_match:
            close_lists()
            if in_blockquote:
                html_lines.append("</blockquote>")
                in_blockquote = False
            leading_tags = heading_match.group(1).strip()
            level = len(heading_match.group(2))
            content = heading_match.group(3).strip()
            if leading_tags:
                html_lines.append(leading_tags)
            html_lines.append(f'<h{level} id="{slugify(content)}">{render_inline(content)}</h{level}>')
            continue

        if stripped in ("---", "***"):
            close_lists()
            html_lines.append("<hr/>")
            continue

        if stripped.startswith("> "):
            if not in_blockquote:
                close_lists()
                html_lines.append("<blockquote>")
                in_blockquote = True
            content = stripped[2:]
            html_lines.append(render_inline(content))
            continue
        else:
            if in_blockquote:
                html_lines.append("</blockquote>")
                in_blockquote = False

        ul_match = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if ul_match:
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{render_inline(ul_match.group(1))}</li>")
            continue

        ol_match = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if ol_match:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{render_inline(ol_match.group(1))}</li>")
            continue

        close_lists()

        # Inline conversions (leave raw HTML intact)
        if stripped == "[TOC]":
            toc_items = []
            for level, title, slug in headings:
                toc_items.append(
                    f'<li class="toc-level-{level}"><a href="#{slug}">{title}</a></li>',
                )
            html_lines.append(
                '<nav class="toc"><ul>' + "".join(toc_items) + "</ul></nav>",
            )
            continue

        html_lines.append(f"<p>{render_inline(line)}</p>")

    close_lists()
    if in_blockquote:
        html_lines.append("</blockquote>")
    if in_code:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)


def _render_markdown_document(markdown_text: str) -> str:
    body = _render_markdown_fallback(markdown_text)
    wrapped = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>body{max-width:900px;margin:24px auto;padding:0 16px;"
        "font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "line-height:1.55;} img{max-width:100%;} pre{background:#f6f6f6;padding:12px;overflow:auto;}"
        ".toc ul{list-style:none;padding-left:0;} .toc li{margin:4px 0;}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )
    return wrapped


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
    except Exception:
        return False

    return any(marker in head for marker in RISKY_REPLAY_MARKERS)


def _apply_archive_replay_headers(response: HttpResponse, *, fullpath: Path, content_type: str, is_archive_replay: bool) -> HttpResponse:
    if not is_archive_replay:
        return response

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-ArchiveBox-Security-Mode", SERVER_CONFIG.SERVER_SECURITY_MODE)

    if SERVER_CONFIG.SHOULD_NEUTER_RISKY_REPLAY and _is_risky_replay_document(fullpath, content_type):
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


def serve_static_with_byterange_support(request, path, document_root=None, show_indexes=False, is_archive_replay: bool = False):
    """
    Overrides Django's built-in django.views.static.serve function to support byte range requests.
    This allows you to do things like seek into the middle of a huge mp4 or WACZ without downloading the whole file.
    https://github.com/satchamo/django/commit/2ce75c5c4bee2a858c0214d136bfcd351fcde11d
    """
    assert document_root
    path = posixpath.normpath(path).lstrip("/")
    fullpath = Path(safe_join(document_root, path))
    if os.access(fullpath, os.R_OK) and fullpath.is_dir():
        if request.GET.get("download") == "zip" and show_indexes:
            return _build_directory_zip_response(
                fullpath,
                path,
                is_archive_replay=is_archive_replay,
                use_async_stream=hasattr(request, "scope"),
            )
        if show_indexes:
            response = _render_directory_index(request, path, fullpath)
            return _apply_archive_replay_headers(response, fullpath=fullpath, content_type="text/html", is_archive_replay=is_archive_replay)
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
                not_modified.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
                not_modified.headers["Last-Modified"] = http_date(statobj.st_mtime)
                return _apply_archive_replay_headers(not_modified, fullpath=fullpath, content_type="", is_archive_replay=is_archive_replay)

    content_type, encoding = mimetypes.guess_type(str(fullpath))
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

    # Respect the If-Modified-Since header for non-markdown responses.
    if not (content_type.startswith("text/plain") or content_type.startswith("text/html")):
        if not static.was_modified_since(request.META.get("HTTP_IF_MODIFIED_SINCE"), statobj.st_mtime):
            return _apply_archive_replay_headers(
                HttpResponseNotModified(),
                fullpath=fullpath,
                content_type=content_type,
                is_archive_replay=is_archive_replay,
            )

    # Wrap text-like outputs in HTML when explicitly requested for iframe previewing.
    if preview_as_text_html:
        try:
            max_preview_size = 10 * 1024 * 1024
            if statobj.st_size <= max_preview_size:
                decoded = fullpath.read_text(encoding="utf-8", errors="replace")
                wrapped = _render_text_preview_document(decoded, fullpath.name)
                response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
                response.headers["Last-Modified"] = http_date(statobj.st_mtime)
                if etag:
                    response.headers["ETag"] = etag
                    response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
                else:
                    response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
                response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
                if encoding:
                    response.headers["Content-Encoding"] = encoding
                return _apply_archive_replay_headers(
                    response,
                    fullpath=fullpath,
                    content_type="text/html; charset=utf-8",
                    is_archive_replay=is_archive_replay,
                )
        except Exception:
            pass

    if preview_as_image_html:
        try:
            preview_query = request.GET.copy()
            preview_query.pop("preview", None)
            raw_image_url = request.path
            if preview_query:
                raw_image_url = f"{raw_image_url}?{urlencode(list(preview_query.lists()), doseq=True)}"
            wrapped = _render_image_preview_document(raw_image_url, fullpath.name)
            response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
            response.headers["Last-Modified"] = http_date(statobj.st_mtime)
            if etag:
                response.headers["ETag"] = etag
                response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
            response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
            if encoding:
                response.headers["Content-Encoding"] = encoding
            return _apply_archive_replay_headers(
                response,
                fullpath=fullpath,
                content_type="text/html; charset=utf-8",
                is_archive_replay=is_archive_replay,
            )
        except Exception:
            pass

    # Heuristic fix: some archived HTML outputs (e.g. mercury content.html)
    # are stored with HTML-escaped markup or markdown sources. If so, render sensibly.
    if content_type.startswith("text/plain") or content_type.startswith("text/html"):
        try:
            max_unescape_size = 10 * 1024 * 1024  # 10MB cap to avoid heavy memory use
            if statobj.st_size <= max_unescape_size:
                raw = fullpath.read_bytes()
                decoded = raw.decode("utf-8", errors="replace")
                escaped_count = decoded.count("&lt;") + decoded.count("&gt;")
                tag_count = decoded.count("<")
                if escaped_count and escaped_count > tag_count * 2:
                    decoded = html.unescape(decoded)
                markdown_candidate = _extract_markdown_candidate(decoded)
                if _looks_like_markdown(markdown_candidate):
                    wrapped = _render_markdown_document(markdown_candidate)
                    response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
                    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
                    if etag:
                        response.headers["ETag"] = etag
                        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
                    else:
                        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
                    response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
                    if encoding:
                        response.headers["Content-Encoding"] = encoding
                    return _apply_archive_replay_headers(
                        response,
                        fullpath=fullpath,
                        content_type="text/html; charset=utf-8",
                        is_archive_replay=is_archive_replay,
                    )
                if escaped_count and escaped_count > tag_count * 2:
                    response = HttpResponse(decoded, content_type=content_type)
                    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
                    if etag:
                        response.headers["ETag"] = etag
                        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
                    else:
                        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
                    response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
                    if encoding:
                        response.headers["Content-Encoding"] = encoding
                    return _apply_archive_replay_headers(
                        response,
                        fullpath=fullpath,
                        content_type=content_type,
                        is_archive_replay=is_archive_replay,
                    )
        except Exception:
            pass

    # setup response object
    ranged_file = RangedFileReader(open(fullpath, "rb"))
    response = StreamingHttpResponse(ranged_file, content_type=content_type)
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    if etag:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = f"{_cache_policy()}, max-age=60, stale-while-revalidate=300"
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
                response["Content-Range"] = "bytes %d-%d/%d" % (start, stop - 1, size)
                response["Content-Length"] = stop - start
                response.status_code = 206
    if encoding:
        response.headers["Content-Encoding"] = encoding
    return _apply_archive_replay_headers(response, fullpath=fullpath, content_type=content_type, is_archive_replay=is_archive_replay)


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
        raise Http404("'%s' could not be found" % path)
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
            if start < 0:
                start = 0
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
        self.f.seek(self.start)
        position = self.start
        while position < self.stop:
            data = self.f.read(min(self.block_size, self.stop - position))
            if not data:
                break

            yield data
            position += self.block_size
