"""On-demand portable exports of native crawl snapshots, without export state."""

import html
import json
import posixpath
import re
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from archivebox.core.models import ArchiveResult
from archivebox.misc.logging_util import printable_filesize
from archivebox.misc.serve_static import (
    Resources,
    _rewrite_css_sources_to_responses,
    _rewrite_html_image_sources_to_responses,
    rewrite_navigation_links,
)

from .wacz import replay_assets, write_site_wacz


HTML_PLUGINS = ("singlefile", "chrome_extension_singlefile", "dom", "wget", "readability", "defuddle")
CSS_URL = re.compile(r"(?:url\(\s*|@import\s+)[\"']?([^\s\"'()]+)", re.IGNORECASE)


def captured_pages(snapshots):
    """Use the same saved HTML preference as original-domain replay."""
    pages = []
    seen = set()
    for snapshot in snapshots:
        key = urlsplit(snapshot.url)._replace(scheme="", fragment="").geturl()
        if key in seen:
            continue
        results = list(snapshot.archiveresult_set.all())
        successful = [result for result in results if result.status == ArchiveResult.StatusChoices.SUCCEEDED]
        root = snapshot.output_dir.resolve()
        for plugin in HTML_PLUGINS:
            path = snapshot.plugin_output_path(plugin, archive_results=successful)
            if not path:
                continue
            source = (root / path).resolve()
            if source.is_relative_to(root) and source.is_file() and source.suffix.lower() in {".html", ".htm"}:
                pages.append((snapshot.pk, snapshot.url, root, source.relative_to(root).as_posix(), key))
                seen.add(key)
                break
    return pages


def _write_page(destination, snapshot_id, page_url, root, path, links, report_bytes):
    prefix = f"pages/{snapshot_id}/"
    pending = [path]
    written = set()
    asset_roots = [root / Path(path).parts[0], root / "responses"]
    while pending:
        relative = pending.pop()
        if relative in written:
            continue
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            continue
        written.add(relative)
        target = destination / prefix / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        resources = []
        if source.suffix.lower() in {".html", ".htm", ".css"}:
            text = source.read_bytes().decode("utf-8", errors="surrogateescape")
            if source.suffix.lower() == ".css":
                text, _ = _rewrite_css_sources_to_responses(text, root, relative)
                resources = CSS_URL.findall(text)
            else:
                text, _ = _rewrite_html_image_sources_to_responses(text, root, relative, page_url)
                parsed = Resources(text)
                parsed.feed(text)
                resources = [value for _, _, value in parsed.spans] + CSS_URL.findall(text)
                navigation = Resources(text, navigation=True)
                navigation.feed(text)
                base = urljoin(page_url, navigation.base_href or "")
                keys = {urlsplit(urljoin(base, href))._replace(scheme="", fragment="").geturl() for _, _, href in navigation.spans}
                targets = {key: posixpath.relpath(links[key], posixpath.dirname(prefix + relative)) for key in keys if key in links}
                script = posixpath.relpath("archivebox-links.js", posixpath.dirname(prefix + relative))
                text, _ = rewrite_navigation_links(text, page_url, targets, asset_base="./", external_links_script=script)
            content = text.encode("utf-8", errors="surrogateescape")
            report_bytes(len(content))
            target.write_bytes(content)
        else:
            with source.open("rb") as original, target.open("xb") as exported:
                while chunk := original.read(1024 * 1024):
                    report_bytes(len(chunk))
                    exported.write(chunk)
        # Stay within the selected output and captured responses, excluding
        # browser profiles, native collection metadata and process logs.
        for resource in resources:
            parsed_url = urlsplit(resource)
            if parsed_url.scheme or parsed_url.netloc or not parsed_url.path or parsed_url.path.startswith("/"):
                continue
            candidate = (source.parent / unquote(parsed_url.path)).resolve()
            if any(candidate.is_relative_to(asset_root) for asset_root in asset_roots) and candidate.suffix.lower() not in {".log", ".pid"}:
                pending.append(candidate.relative_to(root).as_posix())


def write_static_site(destination, snapshots, *, title, progress, max_bytes=0):
    pages = captured_pages(snapshots)
    if not pages:
        raise ValueError("No saved HTML pages are available. Capture this site with SingleFile, DOM or wget enabled first.")
    # Prefer the site root as the entry point; snapshots arrive newest-first.
    pages.sort(key=lambda page: (urlsplit(page[1]).path not in {"", "/"}, len(urlsplit(page[1]).path)))
    links = {key: f"pages/{snapshot_id}/{path}" for snapshot_id, _, _, path, key in pages}
    (destination / "archivebox-links.js").write_text(
        "globalThis.__archiveboxExport={links:"
        + json.dumps(links).replace("<", "\\u003c")
        + ",base:new URL('.',document.currentScript.src).href};",
    )
    size = 0
    reported_at = 0.0
    completed = 0

    def report_bytes(count):
        nonlocal size, reported_at
        if max_bytes and size + count > max_bytes:
            raise ValueError(f"Static HTML export exceeds the {printable_filesize(max_bytes)} ({max_bytes} bytes) limit.")
        size += count
        now = time.monotonic()
        if now - reported_at >= 1:
            progress({"pages": completed, "total_pages": len(pages), "bytes": size})
            reported_at = now

    for index, (snapshot_id, page_url, root, path, _) in enumerate(pages):
        _write_page(destination, snapshot_id, page_url, root, path, links, report_bytes)
        completed = index + 1
        progress({"pages": completed, "total_pages": len(pages), "bytes": size})
    start = links[pages[0][4]]
    escaped = html.escape(quote(start, safe="/"), quote=True)
    (destination / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f'<meta http-equiv="refresh" content="0;url={escaped}"><a href="{escaped}">Open saved site</a>',
    )
    (destination / "pages.json").write_text(json.dumps([{"url": page_url, "path": links[key]} for _, page_url, _, _, key in pages]))
    return len(pages)


def write_replay_site(destination, snapshots, *, title, config, progress, player=True):
    # Check player installation before copying a potentially very large site.
    assets = replay_assets(config) if player else {}
    recordings = []
    main_url = ""
    for snapshot in snapshots:
        results = list(snapshot.archiveresult_set.all())
        root = snapshot.output_dir.resolve()
        for result in results:
            if result.status != ArchiveResult.StatusChoices.SUCCEEDED:
                continue
            # Native output metadata is sufficient. Scanning every saved file
            # or loading hashes.json would traverse unrelated media outputs.
            relative = result.embed_path_db()
            if not relative or not relative.lower().endswith(".wacz"):
                continue
            path = (root / relative).resolve()
            if path.is_relative_to(root) and path.suffix.lower() == ".wacz" and path.is_file():
                recordings.append(path)
                if not main_url or (urlsplit(snapshot.url).path in {"", "/"} and urlsplit(main_url).path not in {"", "/"}):
                    main_url = snapshot.url
    with (destination / "site.wacz").open("xb") as output:
        count = write_site_wacz(output, recordings, title=title, main_url=main_url, progress=progress)
    if player:
        for name, data in assets.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (destination / "index.html").write_text(
            '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{html.escape(title)}</title><script src="replay/ui.js"></script>'
            "<style>html,body{margin:0;height:100%}replay-web-page{display:block;height:100%}</style></head><body>"
            '<replay-web-page source="./site.wacz" replaybase="./replay/" embed="default" deepLink '
            f'url="{html.escape(main_url, quote=True)}"></replay-web-page>'
            '<script>if(location.protocol==="file:")document.body.textContent='
            '"Upload this folder to an HTTPS website, or use the Static HTML export to open saved pages directly.";</script></body></html>',
        )
    return count
