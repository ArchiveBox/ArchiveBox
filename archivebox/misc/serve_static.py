import asyncio
import html
import json
import mimetypes
import os
import posixpath
import queue
import re
import stat
import sys
import threading
import time
import zipfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin

from django.contrib.staticfiles import finders
from django.core.handlers.asgi import ASGIRequest
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.template import TemplateDoesNotExist, loader
from django.utils._os import safe_join
from django.utils.http import http_date
from django.utils.translation import gettext as _
from django.views import static
from markdown import markdown

from archivebox.config.common import get_config
from archivebox.misc.logging_util import printable_filesize
from archivebox.plugins.discovery import render_plugin_full_response

_HASHES_CACHE: dict[Path, tuple[float, dict[str, str]]] = {}
DIRECTORY_PREVIEW_MAX_BYTES = 100 * 1024
FAVICON_CACHE_CONTROL = "public, max-age=31536000, s-maxage=31536000, immutable"
IMG_SRC_ATTR_RE = re.compile(r'(<img\b[^>]*?\s(?:src|data-src)=["\'])([^"\']+)(["\'])', re.IGNORECASE)
TRANSFORMED_HTML_PREVIEW_STYLE = """<style id="archivebox-static-html-preview-style">
html {
    width: 100%;
    min-width: 100%;
    background: #fff;
}
body {
    box-sizing: border-box;
    width: min(100%, 72rem);
    max-width: none;
    min-height: 100vh;
    margin: 0 auto;
    padding: clamp(1rem, 3vw, 2rem);
    background: #fff;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55;
}
body > * {
    max-width: 100%;
}
img:not([width]):not([height]) {
    max-width: min(100%, 12rem);
    max-height: 12rem;
    width: auto;
    height: auto;
    object-fit: contain;
}
a > img:not([width]):not([height]) {
    max-width: min(100%, 2.5rem);
    max-height: 2.5rem;
}
</style>"""


def add_replay_archive_fallbacks(response: HttpResponse) -> HttpResponse:
    """Repair missing responsive images and equivalent recorded X API URLs.

    X's client uses api.x.com/graphql without its original CSRF cookie, while
    authenticated capture uses x.com/i/api/graphql. Repair only GETs for that
    exact endpoint alias (also twitter.com), with an identical indexed query in
    the same local archive. Never reuse credentials or fetch a live API.

    WHY: a recorder saves the image Chrome selected, not every srcset candidate.
    Replaying at another viewport/DPR can select an uncaptured URL (the motivating
    case was Drive's missing 2x logo with its 1x logo already in the same WACZ).
    WACZ requests are answered inside Webrecorder's service worker, so a Django
    404 handler cannot repair them. Append this adapter when serving that worker;
    do not change captures, request more live assets, or resize the recorded page.

    For images, only a GET that already returned 404 is eligible. The worker reads the
    referring HTML from the SAME archive and tries src/srcset candidates declared
    on that img or its enclosing picture. It never guesses filename substitutions
    or borrows an unrelated nearby image. The original response wins on absent
    metadata, unsupported worker APIs, parse errors, timeout, or failed candidates.
    This deliberately does not promise to fix JS-only srcsets, CSS backgrounds,
    corrupt images returning 200, or pages whose archived HTML is too large.

    Keep this self-contained in the static-file server: it is a replay repair,
    independent of capture execution. Feature detection makes upstream
    worker changes disable the repair rather than break ordinary replay. The
    archive's HTML/ZIP bytes and successful HTTP responses remain untouched.
    """
    if (
        response.status_code != 200
        or response.streaming
        or not response.has_header("Service-Worker-Allowed")
        or "javascript" not in response.get("Content-Type", "")
    ):
        return response
    script = rb"""
;(() => {
  try {
    const replay = self.sw;
    if (!replay || typeof replay.handleFetch !== "function" ||
        typeof replay.getResponseFor !== "function" || !replay.collections ||
        replay.proxyOriginMode || replay.topFramePassthrough || replay.__abxArchiveFallbacks) return;
    const original = replay.handleFetch;
    const documents = new Map();
    const decode = value => value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[\da-f]+);/gi, entity => {
      const named = {"&amp;":"&", "&quot;":'"', "&apos;":"'", "&lt;":"<", "&gt;":">"};
      return named[entity.toLowerCase()] || String.fromCodePoint(
        entity[2].toLowerCase() === "x" ? parseInt(entity.slice(3), 16) : parseInt(entity.slice(2), 10));
    });
    const attributes = tag => {
      const attrs = {};
      for (const m of tag.matchAll(/([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/g)) {
        attrs[m[1].toLowerCase()] = decode(m[2] ?? m[3] ?? m[4]);
      }
      return attrs;
    };
    const sourceSet = value => {
      // URLs may contain commas (e.g. image-CDN transforms). Like HTML's
      // srcset tokenizer, consume a URL through whitespace, then descriptors.
      const urls = [];
      let rest = value || "";
      while (rest && urls.length < 64) {
        rest = rest.replace(/^[\s,]+/, "");
        const token = rest.match(/^\S+/)?.[0];
        if (!token) break;
        urls.push(token.replace(/,+$/, ""));
        rest = rest.slice(token.length);
        if (!token.endsWith(",")) rest = rest.replace(/^[^,]*(?:,|$)/, "");
      }
      return urls;
    };
    const splitReplay = (url, prefix) => {
      if (!url.startsWith(prefix)) return null;
      return url.slice(prefix.length).match(/^((?::[^/]+\/)?\d{0,14})(?:[a-z]+_)?\/((?:https?:)?\/\/.+)$/);
    };
    replay.handleFetch = async function(event) {
      // Never catch/retry the original operation: preserve its normal behavior.
      const response = await original.call(this, event);
      const request = event.request;
      if (response.status !== 404 || request.method !== "GET" ||
          !["image", ""].includes(request.destination)) return response;
      let expired = false, timer;
      try {
        const repair = async () => {
          if (!request.url.startsWith(this.replayPrefix)) return response;
          const name = this.collections.root || request.url.slice(this.replayPrefix.length).split("/", 1)[0];
          const collection = await this.collections.getColl(name);
          // Do not operate on live/proxy collections or remote source archives.
          // lookupUrl is the archive index API, absent on the live proxy store.
          if (!collection || typeof collection.store?.lookupUrl !== "function" || collection.liveRedirectOnNotFound ||
              new URL(collection.config.sourceUrl).origin !== self.location.origin) return response;
          const missing = splitReplay(request.url, collection.prefix);
          const referring = splitReplay(request.referrer, collection.prefix);
          if (!missing || !referring) return response;
          const archiveURL = url => collection.prefix + referring[1] + "id_/" + url;
          const read = url => this.getResponseFor(new Request(archiveURL(url), {
            credentials: "same-origin", redirect: "manual", signal: request.signal,
          }), event);
          if (request.destination !== "image") {
            const api = missing[2].match(/^https:\/\/api\.(x|twitter)\.com(\/graphql\/[\w-]+\/\w+)(\?.*)?$/);
            if (!api || new URL(referring[2]).origin !== `https://${api[1]}.com`) return response;
            const url = `https://${api[1]}.com/i/api${api[2]}${api[3] || ""}`;
            const alternative = await read(url);
            // Reading loads the relevant WACZ index block. Require an exact
            // indexed URL too: upstream fuzzy matching must not substitute a
            // different GraphQL query, operation, or authenticated response.
            const indexed = await collection.store.lookupUrl(url, 0);
            if (expired || !indexed || indexed.url !== url || alternative.status !== 200 ||
                !alternative.headers.get("content-type")?.includes("application/json")) return response;
            const headers = new Headers(alternative.headers);
            headers.set("X-ArchiveBox-API-Alias", url);
            headers.set("Cache-Control", "no-store");
            return new Response(alternative.body, {status:200, headers});
          }
          const key = archiveURL(referring[2]);
          if (!documents.has(key)) {
            // Cache only candidate metadata, never whole HTML or image bodies.
            // Both entry count and HTML reads are bounded; WACZ range loading
            // remains the upstream replay engine's responsibility.
            if (documents.size >= 16) documents.delete(documents.keys().next().value);
            documents.set(key, (async () => {
              const html = await read(referring[2]);
              if (html.status !== 200 || !html.headers.get("content-type")?.includes("text/html")) return [];
              const reader = html.body.getReader(), decoder = new TextDecoder();
              let text = "", size = 0;
              try {
                while (true) {
                  const chunk = await reader.read();
                  if (chunk.done) break;
                  size += chunk.value.byteLength;
                  if (expired || size > 2 * 1024 * 1024) return [];
                  text += decoder.decode(chunk.value, {stream:true});
                }
                text += decoder.decode();
              } finally {await reader.cancel().catch(() => {});}
              // Ignore tag-shaped strings in scripts/comments. Parsing is
              // intentionally conservative; an odd/malformed page stays broken
              // instead of acquiring an unrelated "similar looking" image.
              text = text.replace(/<!--[\s\S]*?-->|<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, "");
              const groups = [];
              let base = referring[2], picture = null;
              const absolute = value => {
                try {
                  const url = new URL(value, base);
                  if (!/^https?:$/.test(url.protocol) || url.username || url.password) return null;
                  url.hash = "";
                  return url.href;
                } catch {return null;}
              };
              for (const token of text.matchAll(/<\/?(?:base|picture|source|img)\b(?:"[^"]*"|'[^']*'|[^'">])*>/gi)) {
                const tag = token[0], attrs = attributes(tag);
                if (/^<base\b/i.test(tag)) {if (attrs.href) base = absolute(attrs.href) || base; continue;}
                if (/^<picture\b/i.test(tag)) {picture = []; continue;}
                if (/^<\/picture\b/i.test(tag)) {picture = null; continue;}
                const urls = [...new Set([attrs.src, ...sourceSet(attrs.srcset)].filter(Boolean).map(absolute).filter(Boolean))];
                if (/^<source\b/i.test(tag)) {if (picture) picture.push(...urls); continue;}
                if (!attrs.srcset && !picture?.length) continue;
                groups.push([...new Set([...urls, ...(picture || [])])].slice(0, 64));
                if (groups.length >= 512) break;
              }
              return groups;
            })());
          }
          const groups = await documents.get(key);
          const failed = new URL(missing[2], referring[2]); failed.hash = "";
          const candidates = groups.find(group => group.includes(failed.href));
          if (!candidates) return response;
          // Prefer the img's explicit src, then alternatives in declaration
          // order. Limit extra archive lookups, and never follow redirects.
          for (const url of candidates.filter(url => url !== failed.href).slice(0, 6)) {
            if (expired) break;
            const alternative = await read(url);
            if (alternative.status !== 200 || !alternative.headers.get("content-type")?.startsWith("image/")) continue;
            if (expired) break;
            const headers = new Headers(alternative.headers);
            headers.set("X-ArchiveBox-Image-Fallback", url);
            headers.set("Cache-Control", "no-store");
            return new Response(alternative.body, {status:200, headers});
          }
          return response;
        };
        return await Promise.race([
          repair().catch(() => response),
          new Promise(resolve => {timer = setTimeout(() => {expired = true; resolve(response);}, 1500);}),
        ]);
      } catch {return response;}
      finally {expired = true; clearTimeout(timer);}
    };
    replay.__abxArchiveFallbacks = true;
  } catch { /* Optional repair must never prevent the worker from starting. */ }
})();
"""
    try:
        body = response.content
        if b"self.sw=" not in body or b"__abxArchiveFallbacks" in body:
            return response
        response.content = body + script
        # Upstream headers describe the unmodified worker. Revalidate this
        # generated asset so existing captures can receive the repair too.
        for header in ("ETag", "Last-Modified", "Content-Length"):
            if response.has_header(header):
                del response[header]
        response["Cache-Control"] = "no-cache"
    except Exception:
        pass
    return response


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
    if any(part.casefold() == ".persona" for part in Path(rel_path).parts):
        raise Http404("Browser runtime files are not archive outputs")
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

    resolved_path = posixpath.join(*resolved_parts) if resolved_parts else ""
    return Path(safe_join(document_root, resolved_path)), resolved_path


def _cache_policy(config=None, **config_kwargs) -> str:
    config = config or get_config(resolve_plugins=False, **config_kwargs)
    return "public" if config.PERMISSIONS == "public" else "private"


def _format_direntry_timestamp(stat_result: os.stat_result) -> str:
    timestamp = stat_result.st_birthtime if sys.platform == "darwin" else stat_result.st_mtime
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M")


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

    root = root.resolve()
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirname for dirname in dirnames if not dirname.startswith("."))
        for filename in sorted(name for name in filenames if not name.startswith(".")):
            entry = Path(current_root) / filename
            if entry.resolve().is_relative_to(root):
                yield entry


def _build_directory_zip_response(
    fullpath: Path,
    path: str,
    *,
    is_archive_replay: bool,
    use_async_stream: bool,
    config=None,
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
        except (OSError, RuntimeError, TypeError, ValueError, zipfile.BadZipFile) as err:
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


async def _stream_ranged_file_async(ranged_file: "RangedFileReader"):
    iterator = iter(ranged_file)
    try:
        while True:
            chunk = await asyncio.to_thread(next, iterator, None)
            if chunk is None:
                break
            yield chunk
    finally:
        ranged_file.close()


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
        preview_kind = ""
        mime = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
        if entry.is_file() and stat_result.st_size < DIRECTORY_PREVIEW_MAX_BYTES:
            if mime.startswith("image/"):
                preview_kind = "image"
            elif (
                mime.startswith("text/")
                or re.search(r"(?:^|[.+/-])(?:json|xml|javascript|ecmascript|yaml|toml|graphql|sql)(?:[.+/-]|$)", mime)
                or entry.suffix.lower() in {".log", ".jsonl", ".toml"}
            ):
                preview_kind = "text"
        entries.append(
            {
                "name": url,
                "url": url,
                "preview_kind": preview_kind,
                "mimetype": "Directory" if entry.is_dir() else mime,
                "size_bytes": 0 if entry.is_dir() else stat_result.st_size,
                "is_dir": entry.is_dir(),
                "size": "—" if entry.is_dir() else printable_filesize(stat_result.st_size),
                "timestamp": _format_direntry_timestamp(stat_result),
            },
        )

    zip_query = request.GET.copy()
    zip_query["download"] = "zip"
    zip_url = quote(request.path, safe="/")
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

MARKDOWN_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+(?:\([^)]*\)[^)\s]*)*)\)")
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


def _encoded_responses_image_url(image_url: str, page_url: str | None) -> str | None:
    raw_url = str(image_url or "").strip()
    if not raw_url or raw_url.startswith(("#", "data:", "blob:", "about:", "javascript:")):
        return None

    absolute_url = urljoin(page_url or "", raw_url)
    if not absolute_url.startswith(("http://", "https://")):
        return None

    return quote(absolute_url, safe="").replace("%", "_")


def _index_responses_paths_for_html_images(
    snapshot_root: Path,
    html_rel_path: str,
    encoded_urls: set[str],
) -> dict[str, str]:
    responses_root = snapshot_root / "responses"
    if not encoded_urls or not responses_root.is_dir():
        return {}

    best_matches: dict[str, str] = {}
    image_matches: set[str] = set()
    # Optional responses plugin file contract: index.jsonl records contain method,
    # url, status, and a path relative to responses/. No plugin code is imported.
    # Legacy captures without an index still use the filename lookup below.
    # The index retains complete URLs even when response filenames are shortened.
    index = responses_root / "index.jsonl"
    if index.is_file():
        with index.open(errors="replace") as records:
            for line in records:
                try:
                    record = json.loads(line)
                    encoded = _encoded_responses_image_url(record.get("url", ""), None)
                    if encoded not in encoded_urls or record.get("method") != "GET" or record.get("status") != 200:
                        continue
                    candidate = (responses_root / record.get("path", "")).resolve()
                    if not candidate.is_relative_to(responses_root.resolve()) or not candidate.is_file():
                        continue
                    best_matches[encoded] = posixpath.relpath(candidate, start=snapshot_root / posixpath.dirname(html_rel_path))
                    image_matches.add(encoded)
                except (ValueError, TypeError, AttributeError):
                    continue
    image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
    for candidate in responses_root.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            rel_path = candidate.relative_to(snapshot_root)
        except ValueError:
            continue
        relative_match = posixpath.relpath(rel_path.as_posix(), start=posixpath.dirname(html_rel_path) or ".")
        candidate_name = candidate.name
        is_image = candidate.suffix.lower() in image_suffixes
        for encoded_url in encoded_urls:
            if encoded_url in image_matches or f"__GET__{encoded_url}" not in candidate_name:
                continue
            best_matches[encoded_url] = relative_match
            if is_image:
                # Preserve the old rglob behavior: the first image match wins,
                # otherwise the last matching response file is used.
                image_matches.add(encoded_url)
    return best_matches


def _rewrite_html_image_sources_to_responses(
    html_text: str,
    snapshot_root: Path,
    html_rel_path: str,
    page_url: str | None,
) -> tuple[str, int]:
    encoded_urls_by_src: dict[str, str | None] = {}
    for match in IMG_SRC_ATTR_RE.finditer(html_text):
        image_url = html.unescape(match.group(2))
        if image_url not in encoded_urls_by_src:
            encoded_urls_by_src[image_url] = _encoded_responses_image_url(image_url, page_url)

    # Optional dom plugin artifact: dom/output.html. Only image src and
    # data-canonical-src attributes are read; no scripts or plugin code execute.
    # Absence of this artifact simply disables proxy-to-original aliases.
    aliases: dict[str, str] = {}

    class ImageAliases(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            original = attrs.get("data-canonical-src")
            proxy = attrs.get("src")
            if tag == "img" and original and proxy:
                original_key = _encoded_responses_image_url(original, page_url)
                proxy_key = _encoded_responses_image_url(proxy, page_url)
                if original_key and proxy_key:
                    aliases[original_key] = proxy_key

    dom = snapshot_root / "dom" / "output.html"
    if dom.is_file() and dom.stat().st_size <= 10 * 1024 * 1024:
        ImageAliases().feed(dom.read_text(errors="replace"))
    wanted = {encoded for encoded in encoded_urls_by_src.values() if encoded}
    response_paths = _index_responses_paths_for_html_images(
        snapshot_root,
        html_rel_path,
        wanted | {aliases[key] for key in wanted if key in aliases},
    )
    rewrites = 0

    def replace_src(match: re.Match[str]) -> str:
        nonlocal rewrites
        image_url = html.unescape(match.group(2))
        encoded_url = encoded_urls_by_src.get(image_url)
        local_path = response_paths.get(encoded_url or "") or response_paths.get(aliases.get(encoded_url or "", ""))
        if not local_path:
            return match.group(0)
        rewrites += 1
        return f"{match.group(1)}{html.escape(local_path, quote=True)}{match.group(3)}"

    return IMG_SRC_ATTR_RE.sub(replace_src, html_text), rewrites


def _rewrite_html_image_sources_for_request(
    request,
    html_text: str,
    document_root: Path | None,
    html_rel_path: str,
) -> tuple[str, int]:
    if not document_root:
        return html_text, 0
    try:
        return _rewrite_html_image_sources_to_responses(
            html_text,
            document_root,
            html_rel_path,
            request.__dict__.get("archivebox_snapshot_url"),
        )
    except (OSError, ValueError, TypeError, RecursionError):
        # Saved plugin artifacts are optional and may be incomplete, malformed,
        # or removed concurrently. Image enrichment must not break file replay.
        return html_text, 0


def _apply_transformed_html_preview_style(html_text: str) -> str:
    if "archivebox-static-html-preview-style" in html_text:
        return html_text
    if re.search(r"</head\s*>", html_text, flags=re.IGNORECASE):
        return re.sub(r"</head\s*>", f"{TRANSFORMED_HTML_PREVIEW_STYLE}\\g<0>", html_text, count=1, flags=re.IGNORECASE)
    return f"{TRANSFORMED_HTML_PREVIEW_STYLE}\n{html_text}"


def _set_transformed_response_headers(
    response,
    fullpath: Path,
    statobj: os.stat_result,
    encoding: str | None,
    cache_policy: str,
) -> None:
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    response.headers["Cache-Control"] = f"{cache_policy}, max-age=60, stale-while-revalidate=300"
    response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
    if encoding:
        response.headers["Content-Encoding"] = encoding


def _render_markdown_document(markdown_text: str) -> str:
    # Saved repository READMEs need the same table/code rendering in every install;
    # an optional dependency silently degraded them to a partial handwritten parser.
    body = markdown(markdown_text, extensions=["extra", "toc", "sane_lists"], output_format="html")
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
        with fullpath.open("rb") as source:
            head = source.read(4096).decode("utf-8", errors="ignore").lower()
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
    cache_policy = getattr(request, "archivebox_cache_policy", None) or _cache_policy(config=config)
    fullpath, path = _resolve_archive_path(document_root, path)
    if os.access(fullpath, os.R_OK) and fullpath.is_dir():
        if request.GET.get("download") == "zip" and show_indexes:
            response = _build_directory_zip_response(
                fullpath,
                path,
                is_archive_replay=is_archive_replay,
                use_async_stream=_is_asgi_request(request),
                config=config,
            )
            response.headers["Cache-Control"] = f"{cache_policy}, max-age=60, stale-while-revalidate=300"
            return response
        if show_indexes:
            response = _render_directory_index(request, path, fullpath)
            response.headers["Cache-Control"] = f"{cache_policy}, max-age=60, stale-while-revalidate=300"
            response.headers["Last-Modified"] = http_date(fullpath.stat().st_mtime)
            return _apply_archive_replay_headers(
                response,
                fullpath=fullpath,
                content_type="text/html",
                is_archive_replay=is_archive_replay,
                config=config,
            )
        raise Http404(_("Directory indexes are not allowed here."))
    if not os.access(fullpath, os.R_OK):
        raise Http404(_("“%(path)s” does not exist") % {"path": fullpath})

    statobj = fullpath.stat()
    # Captured site icons are intentionally shareable even for private snapshots.
    # Only raw icon responses qualify, not generated previews or directory pages.
    favicon_cache_control = (
        FAVICON_CACHE_CONTROL
        if fullpath.stem.lower() == "favicon"
        and fullpath.suffix.lower() in {".ico", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}
        and not request.GET.get("preview")
        else None
    )
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
                not_modified.headers["Cache-Control"] = favicon_cache_control or f"{cache_policy}, max-age=31536000, immutable"
                not_modified.headers["Last-Modified"] = http_date(statobj.st_mtime)
                return _apply_archive_replay_headers(
                    not_modified,
                    fullpath=fullpath,
                    content_type="",
                    is_archive_replay=is_archive_replay,
                    config=config,
                )

    content_type, encoding = mimetypes.guess_type(str(fullpath))
    # Captured favicons retain the conventional .ico filename even when a site
    # returns SVG. Browsers cannot decode SVG served as image/x-icon.
    if fullpath.suffix.lower() == ".ico":
        with fullpath.open("rb") as icon_file:
            icon_head = icon_file.read(4096)
        if re.search(rb"<svg(?:\s|>)", icon_head):
            content_type = "image/svg+xml"
    preserve_plain_text = fullpath.suffix.lower() in {".log", ".sh", ".jsonl"}
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
        and (bool(request.GET.get("raw")) or not content_type.startswith("text/html"))
        and not content_type.startswith("image/svg+xml")
    )
    preview_as_image_html = bool(request.GET.get("preview")) and content_type.startswith("image/")
    # Respect the If-Modified-Since header for non-markdown responses.
    if not content_type.startswith(("text/plain", "text/html")) and not static.was_modified_since(
        request.META.get("HTTP_IF_MODIFIED_SINCE"),
        statobj.st_mtime,
    ):
        not_modified = HttpResponseNotModified()
        not_modified.headers["Cache-Control"] = favicon_cache_control or f"{cache_policy}, max-age=60, stale-while-revalidate=300"
        return _apply_archive_replay_headers(
            not_modified,
            fullpath=fullpath,
            content_type=content_type,
            is_archive_replay=is_archive_replay,
            config=config,
        )

    # A shared archive explorer for ZIP outputs from any plugin. Raw/range
    # requests retain the original bytes for downloads and seekable reads.
    if fullpath.suffix.lower() == ".zip" and request.GET.get("preview") and not request.META.get("HTTP_RANGE"):
        raw_query = request.GET.copy()
        raw_query.pop("preview", None)
        raw_query["raw"] = "1"
        wrapped = loader.get_template("static/zip_index.html").render(
            {
                "title": fullpath.name,
                "output_path": f"{request.path}?{raw_query.urlencode()}",
                "archive_size": statobj.st_size,
            },
        )
        response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
        _set_transformed_response_headers(response, fullpath, statobj, None, cache_policy)
        return _apply_archive_replay_headers(
            response,
            fullpath=fullpath,
            content_type="text/html; charset=utf-8",
            is_archive_replay=is_archive_replay,
            config=config,
        )

    # Wrap text-like outputs in HTML when explicitly requested for iframe previewing.
    if preview_as_text_html:
        try:
            max_preview_size = 10 * 1024 * 1024
            if statobj.st_size <= max_preview_size:
                decoded = fullpath.read_text(encoding="utf-8", errors="replace")
                wrapped = _render_text_preview_document(decoded, fullpath.name)
                response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
                _set_transformed_response_headers(response, fullpath, statobj, encoding, cache_policy)
                return _apply_archive_replay_headers(
                    response,
                    fullpath=fullpath,
                    content_type="text/html; charset=utf-8",
                    is_archive_replay=is_archive_replay,
                    config=config,
                )
        except (OSError, UnicodeDecodeError, ValueError):
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
            _set_transformed_response_headers(response, fullpath, statobj, encoding, cache_policy)
            return _apply_archive_replay_headers(
                response,
                fullpath=fullpath,
                content_type="text/html; charset=utf-8",
                is_archive_replay=is_archive_replay,
                config=config,
            )
        except (OSError, ValueError):
            pass

    if request.GET.get("preview"):
        try:
            raw_query = request.GET.copy()
            raw_query.pop("preview", None)
            raw_output_path = request.path
            if raw_query:
                raw_output_path = f"{raw_output_path}?{raw_query.urlencode()}"
            plugin_replay = render_plugin_full_response(
                fullpath.name,
                raw_output_path,
                wacz_path=fullpath,
                fallback_url=request.archivebox_snapshot_url or "",
                last_modified=http_date(statobj.st_mtime),
                etag=etag or "",
                cache_control=(
                    f"{cache_policy}, max-age=31536000, immutable" if etag else f"{cache_policy}, max-age=60, stale-while-revalidate=300"
                ),
                content_encoding=encoding or "",
            )
            if plugin_replay is not None:
                body, replay_content_type, headers = plugin_replay
                response = HttpResponse(body, content_type=replay_content_type)
                for key, value in headers.items():
                    response.headers[key] = value
                return _apply_archive_replay_headers(
                    response,
                    fullpath=fullpath,
                    content_type=replay_content_type,
                    is_archive_replay=is_archive_replay,
                    config=config,
                )
        except (OSError, RuntimeError, ValueError):
            pass

    # Heuristic fix: some archived HTML outputs are stored with HTML-escaped markup
    # or markdown sources. If so, render sensibly.
    if not request.GET.get("raw") and not preserve_plain_text and content_type.startswith(("text/plain", "text/html", "text/markdown")):
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
                    rewritten_html, rewritten_count = _rewrite_html_image_sources_for_request(request, decoded, document_root, rel_path)
                markdown_candidate = _extract_markdown_candidate(decoded)
                if content_type.startswith("text/markdown") or _looks_like_markdown(markdown_candidate):
                    wrapped = _render_markdown_document(markdown_candidate)
                    wrapped, _rewrite_count = _rewrite_html_image_sources_for_request(request, wrapped, document_root, rel_path)
                    wrapped = _apply_transformed_html_preview_style(wrapped)
                    response = HttpResponse(wrapped, content_type="text/html; charset=utf-8")
                    _set_transformed_response_headers(response, fullpath, statobj, encoding, cache_policy)
                    return _apply_archive_replay_headers(
                        response,
                        fullpath=fullpath,
                        content_type="text/html; charset=utf-8",
                        is_archive_replay=is_archive_replay,
                        config=config,
                    )
                if rewritten_count:
                    rewritten_html = _apply_transformed_html_preview_style(rewritten_html)
                    response = HttpResponse(rewritten_html, content_type=content_type)
                    _set_transformed_response_headers(response, fullpath, statobj, encoding, cache_policy)
                    return _apply_archive_replay_headers(
                        response,
                        fullpath=fullpath,
                        content_type=content_type,
                        is_archive_replay=is_archive_replay,
                        config=config,
                    )
                if escaped_count and escaped_count > tag_count * 2:
                    decoded = _apply_transformed_html_preview_style(decoded)
                    response = HttpResponse(decoded, content_type=content_type)
                    _set_transformed_response_headers(response, fullpath, statobj, encoding, cache_policy)
                    return _apply_archive_replay_headers(
                        response,
                        fullpath=fullpath,
                        content_type=content_type,
                        is_archive_replay=is_archive_replay,
                        config=config,
                    )
        except (OSError, UnicodeDecodeError, ValueError):
            pass

    # setup response object
    ranged_file = RangedFileReader(fullpath.open("rb"))
    response = StreamingHttpResponse(
        _stream_ranged_file_async(ranged_file) if _is_asgi_request(request) else ranged_file,
        content_type=content_type,
    )
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    if etag:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = f"{cache_policy}, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = f"{cache_policy}, max-age=60, stale-while-revalidate=300"
    if is_text_like:
        response.headers["Content-Disposition"] = f'inline; filename="{fullpath.name}"'
    if content_type.startswith("image/"):
        response.headers["Cache-Control"] = f"{cache_policy}, max-age=604800, immutable"
    if favicon_cache_control:
        response.headers["Cache-Control"] = favicon_cache_control

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
    return _apply_archive_replay_headers(
        response,
        fullpath=fullpath,
        content_type=content_type,
        is_archive_replay=is_archive_replay,
        config=config,
    )


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
