"""On-demand portable exports of native crawl snapshots, without export state."""

import html
import json
import os
import posixpath
import re
import time
import shutil
import zipfile
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.misc.logging_util import printable_filesize
from abx_plugins.plugins.base.html import Resources
from archivebox.plugins.discovery import get_snapshot_role_paths, rewrite_plugin_replay_document
from archivebox.misc.serve_static import (
    rewrite_navigation_links,
)

from .wacz import replay_assets, write_site_wacz


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
        root = snapshot.output_dir.resolve()
        for path in get_snapshot_role_paths(snapshot, results, "html_replay"):
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
            # Reserve the source bytes before reading: capped exports must reject
            # an oversized document without first allocating the entire file.
            source_size = source.stat().st_size
            report_bytes(source_size)
            text = source.read_bytes().decode("utf-8", errors="surrogateescape")
            if source.suffix.lower() == ".css":
                text, _ = rewrite_plugin_replay_document(text, snapshot_root=root, rel_path=relative, content_type="text/css")
                resources = CSS_URL.findall(text)
            else:
                text, _ = rewrite_plugin_replay_document(
                    text,
                    snapshot_root=root,
                    rel_path=relative,
                    content_type="text/html",
                    page_url=page_url,
                )
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
            report_bytes(len(content) - source_size)
            target.write_bytes(content)
        else:
            with source.open("rb") as original, target.open("xb") as exported:
                while chunk := original.read(1024 * 1024):
                    report_bytes(len(chunk))
                    exported.write(chunk)
        # Stay within the selected output and captured responses, excluding
        # browser profiles, native collection metadata and process logs.
        for resource in resources:
            parsed_url = urlsplit(html.unescape(resource).strip("\"'"))
            if parsed_url.scheme or parsed_url.netloc or not parsed_url.path or parsed_url.path.startswith("/"):
                continue
            candidate = (source.parent / unquote(parsed_url.path)).resolve()
            if any(candidate.is_relative_to(asset_root) for asset_root in asset_roots) and candidate.suffix.lower() not in {".log", ".pid"}:
                pending.append(candidate.relative_to(root).as_posix())


def write_static_site(destination, snapshots, *, title, progress, max_bytes=0):
    snapshots = list(snapshots)
    if not snapshots:
        raise ValueError("No snapshots match these filters.")
    snapshots_by_id = {snapshot.pk: snapshot for snapshot in snapshots}
    pages = captured_pages(snapshots)
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
            progress({"pages": completed, "total_pages": len(snapshots), "bytes": size})
            reported_at = now

    for index, snapshot in enumerate(snapshots):
        root = snapshot.output_dir.resolve()
        relative_root = Path(snapshot.static_archive_path)
        if relative_root.is_absolute() or ".." in relative_root.parts:
            raise ValueError("Snapshot files must be inside the collection archive.")
        target_root = destination / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        # Include complete saved plugin output trees, including Git dotfiles.
        # Never follow directory links or file links outside the snapshot.
        for current, directories, filenames in os.walk(root):
            directories.sort()
            for filename in sorted(filenames):
                source = Path(current) / filename
                if source.parent == root and filename in {"index.html", "index.json", "index.jsonl"}:
                    continue
                if not source.resolve().is_relative_to(root) or not source.is_file():
                    continue
                target = target_root / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as original, target.open("xb") as copied:
                    while chunk := original.read(1024 * 1024):
                        report_bytes(len(chunk))
                        copied.write(chunk)
        completed = index + 1
        progress({"pages": completed, "total_pages": len(snapshots), "bytes": size})

    previews = {}
    for snapshot_id, page_url, root, path, key in pages:
        _write_page(destination, snapshot_id, page_url, root, path, links, report_bytes)
        snapshot = snapshots_by_id[snapshot_id]
        previews[str(snapshot_id)] = {path: posixpath.relpath(links[key], snapshot.static_archive_path)}

    # The collection index and details are the same renderers used by the CLI
    # and live snapshot UI; only their destination and relative URLs differ.
    queryset = Snapshot.objects.filter(pk__in=[snapshot.pk for snapshot in snapshots]).prefetch_related("tags", "archiveresult_set")
    (destination / "index.html").write_text(queryset.to_html(out_dir=destination, preview_paths=previews))
    (destination / "pages.json").write_text(json.dumps([{"url": page_url, "path": links[key]} for _, page_url, _, _, key in pages]))
    assets = None
    for snapshot in snapshots:
        target_root = destination / snapshot.static_archive_path
        if any(path.suffix.lower() == ".wacz" for path in target_root.rglob("*.wacz")):
            if assets is None:
                from archivebox.config.common import get_config

                assets = replay_assets(get_config())
            for name, data in assets.items():
                target = target_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as asset:
                    asset.write(data)
    final_size = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    report_bytes(final_size - size)
    progress({"pages": len(snapshots), "total_pages": len(snapshots), "bytes": final_size})
    return len(snapshots)


def write_wacz_site(destination, snapshots, *, title, progress):
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
    return count


def export_snapshots_to_directory(queryset, *, destination, format, max_bytes=None, progress=None, title="Snapshots"):
    from archivebox.core.exports import MAX_ARCHIVE_BYTES, selection_digest
    from .export_service import FORMATS

    if format not in FORMATS:
        raise ValueError("Select an archive export format.")
    if format in {"html_zip", "wacz"}:
        max_bytes = min(max_bytes, MAX_ARCHIVE_BYTES) if max_bytes and max_bytes > 0 else MAX_ARCHIVE_BYTES
    max_bytes = max_bytes or 0
    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError("Export destination must be an absolute path.")
    state = {"destination": str(destination), "format": format, "bytes": 0}
    consumed_ids = []

    def report(update):
        if max_bytes and max(update.get("bytes", 0), update.get("total_bytes", 0)) > max_bytes:
            raise ValueError(f"Export exceeds the {printable_filesize(max_bytes)} ({max_bytes} bytes) limit.")
        state.update(update)
        if progress:
            progress(dict(state))

    def snapshots():
        # Each batch is materialized before touching saved files; no open DB cursor
        # spans filesystem work. Slicing retains native CLI ordering and limits.
        offset = 0
        while batch := list(queryset.prefetch_related("archiveresult_set")[offset : offset + 100]):
            consumed_ids.extend(snapshot.pk for snapshot in batch)
            yield from batch
            offset += len(batch)

    destination.mkdir(parents=True, exist_ok=False)
    archive_file = destination / ("site.zip" if format == "html_zip" else "site.wacz")
    try:
        report({})
        if format in {"html", "html_zip"}:
            write_static_site(destination, snapshots(), title=title, progress=report, max_bytes=max_bytes)
        else:
            write_wacz_site(destination, snapshots(), title=title, progress=report)
        if format == "html_zip":
            with zipfile.ZipFile(archive_file, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
                for item in destination.rglob("*"):
                    if item.is_file() and item != archive_file:
                        bundle.write(item, item.relative_to(destination).as_posix())
            if max_bytes and archive_file.stat().st_size > max_bytes:
                raise ValueError(f"Export ZIP exceeds the {printable_filesize(max_bytes)} ({max_bytes} bytes) limit.")
            for item in destination.iterdir():
                if item != archive_file:
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
        if archive_file.is_file() and max_bytes and archive_file.stat().st_size > max_bytes:
            raise ValueError(f"Export archive exceeds the {printable_filesize(max_bytes)} ({max_bytes} bytes) limit.")
        report(
            {
                "complete": True,
                "selection_digest": selection_digest(consumed_ids),
                **({"bytes": archive_file.stat().st_size} if archive_file.is_file() else {}),
            },
        )
        return state
    except Exception as error:
        if format in {"html_zip", "wacz"}:
            # This directory was created exclusively for this export above.
            # Failed downloads must not strand their copied staging trees.
            shutil.rmtree(destination)
        report({"error": str(error), "complete": False})
        raise
