__package__ = "archivebox.core"

import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

EXTENSION_SCREENSHOT_PLUGIN = "chrome_extension_screenshot"
PREVIEW_PLUGINS = ("screenshot", EXTENSION_SCREENSHOT_PLUGIN, "seo", "responses", "favicon")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg", ".ico"}


def positive_int(value):
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return 0


def preview_candidates(results):
    """Select only saved outputs. Never read files or fetch remote metadata."""
    candidates = []
    for result in results:
        files = result.output_files
        if not isinstance(files, dict):
            continue
        for path, info in files.items():
            if not isinstance(path, str) or not isinstance(info, dict) or not positive_int(info.get("size")):
                continue
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                continue
            plugin = result.plugin
            relative = path.removeprefix(f"{plugin}/")
            output_path = path if info.get("root_relative") else f"{plugin}/{path}"
            kind = "image"
            rank = None
            if plugin == "screenshot" and relative == "screenshot.png":
                rank = 0
            elif plugin == EXTENSION_SCREENSHOT_PLUGIN and relative in ("screenshot-1.png", "screenshot.png"):
                rank = 1 if relative == "screenshot-1.png" else 2
            elif (
                plugin == "seo"
                and PurePosixPath(relative).stem == "featured-image"
                and PurePosixPath(relative).suffix.lower() in IMAGE_EXTENSIONS
            ):
                rank = 3
            elif plugin == "responses":
                mime = str(info.get("mimetype") or info.get("mime_type") or "")
                if not (relative.startswith("image/") or (relative.startswith("all/") and mime.startswith("image/"))):
                    continue
                width, height = positive_int(info.get("width")), positive_int(info.get("height"))
                if width and height and (min(width, height) <= 2 or max(width, height) <= 64):
                    continue
                if PurePosixPath(relative).suffix.lower() == ".ico":
                    continue
                rank = 4
                kind = "response"
            elif plugin == "favicon" and relative == "favicon.ico":
                rank = 5
                kind = "favicon"
            if rank is None:
                continue
            width, height = positive_int(info.get("width")), positive_int(info.get("height"))
            # Prefer usable known dimensions; byte size remains the legacy fallback.
            usable = bool(width and height and 0.25 <= width / height <= 4)
            score = (rank, -int(usable), -(width * height if usable else 0), -positive_int(info.get("size")), output_path)
            candidates.append((score, {"path": output_path, "kind": kind, "plugin": plugin, "filename": path}))
    seen = set()
    selected = []
    for _score, candidate in sorted(candidates, key=lambda item: item[0]):
        if candidate["path"] not in seen:
            selected.append(candidate)
            seen.add(candidate["path"])
    return selected


def snapshot_preview_candidates(snapshot):
    if "_preview_candidates" not in snapshot.__dict__:
        results = snapshot.__dict__.get("_preview_results")
        if results is None:
            results = snapshot.__dict__.get("_prefetched_objects_cache", {}).get("archiveresult_set")
        if results is None:
            results = snapshot.archiveresult_set.filter(plugin__in=PREVIEW_PLUGINS).only("plugin", "output_files")
        snapshot._preview_candidates = preview_candidates(results)
    return snapshot._preview_candidates


def render_snapshot_preview(snapshot, url_for_candidate, width="100px", height="100px"):
    candidates = []
    for candidate in snapshot_preview_candidates(snapshot):
        candidates.append({"url": url_for_candidate(candidate), "kind": candidate["kind"]})
    try:
        host = urlsplit(snapshot.url).hostname or "Archive"
    except ValueError:
        host = "Archive"
    host = host.removeprefix("www.")
    hue = int(hashlib.sha256(host.encode()).hexdigest()[:6], 16) % 360
    return mark_safe(
        render_to_string(
            "core/snapshot_thumbnail.html",
            {
                "candidates": json.dumps(candidates),
                "first": candidates[0] if candidates else None,
                "host": host,
                "initial": host[:1].upper(),
                "hue": hue,
                "width": width,
                "height": height,
            },
        ),
    )
