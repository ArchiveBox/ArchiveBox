"""Small, optional saved-artifact summaries for server-rendered link previews."""

import json
from html import unescape
from pathlib import Path

from django.core.exceptions import SuspiciousOperation
from django.utils.html import strip_tags
from django.utils.text import Truncator


def snapshot_metadata(snapshot, *, output_dir=None):
    root = Path(output_dir or snapshot.output_dir).resolve()
    results = snapshot.__dict__.get("_admin_archiveresults")
    if results is None:
        results = snapshot.archiveresult_set.filter(status="succeeded")
    files = {}
    for result in results:
        if result.status == "succeeded":
            for key in result.output_file_map():
                if path := result.output_file_path(key):
                    files[path] = result.plugin

    def read(path, limit=262144):
        if path not in files:
            return ""
        try:
            source = (root / path).resolve()
            if not source.is_relative_to(root):
                return ""
            with source.open("rb") as handle:
                data = handle.read(limit + 1)
            # Never parse truncated JSON or load an unbounded capture into memory.
            if path.endswith(".json") and len(data) > limit:
                return ""
            return data[:limit].decode("utf-8", errors="replace")
        except (OSError, ValueError):
            return ""

    def metadata(path):
        try:
            value = json.loads(read(path))
            return value if isinstance(value, dict) else {}
        except (ValueError, RecursionError):
            return {}

    def plain(value, limit):
        if not isinstance(value, str):
            return ""
        try:
            return Truncator(" ".join(unescape(strip_tags(value)).split())).chars(limit)
        except SuspiciousOperation:
            return ""

    seo = metadata("seo/seo.json")
    article = metadata("readability/article.json")
    title = next(
        (
            text
            for value in (
                seo.get("og:title"),
                seo.get("twitter:title"),
                seo.get("title"),
                article.get("title"),
                snapshot.title,
                snapshot.url,
            )
            if (text := plain(value, 300))
        ),
        "",
    )
    description = next(
        (
            text
            for value in (
                seo.get("og:description"),
                seo.get("twitter:description"),
                seo.get("description"),
                article.get("excerpt"),
                article.get("description"),
            )
            if (text := plain(value, 300))
        ),
        "",
    )
    if not description:
        for path in ("readability/content.txt", "htmltotext/htmltotext.txt"):
            if description := plain(read(path, 16384), 300):
                break
    if not description:
        description = Truncator(f"Archived snapshot of {snapshot.url}").chars(300)
    image = ""
    for plugin in ("screenshot", "chrome_extension_screenshot", "chrome_extension_viewport"):
        for path, owner in files.items():
            if owner != plugin or Path(path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            try:
                source = (root / path).resolve()
                if source.is_relative_to(root) and source.is_file() and source.stat().st_size:
                    image = path
                    break
            except (OSError, ValueError):
                continue
        if image:
            break
    return {"title": title, "description": description, "image_path": image}
