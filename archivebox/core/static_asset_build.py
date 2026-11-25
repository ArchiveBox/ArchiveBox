"""Fingerprint the installed UI assets during the image build."""

import json
import re
from functools import cache
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpRequest


PACKAGE_DIR = Path(__file__).resolve().parents[1]
STATIC_BUILD_FILE = PACKAGE_DIR / "STATIC_CACHE_KEY.json"


def _asset_sources():
    # Only claim immutable bytes for the stock finders and the fixed catalog.
    # User templates and plugin apps can change what a relative URL resolves to.
    if (
        settings.CUSTOM_TEMPLATES_ENABLED
        or settings.USE_I18N
        or settings.LOCALE_PATHS
        or settings.FORMAT_MODULE_PATH
        or list(settings.STATICFILES_DIRS) != [str(PACKAGE_DIR / "templates" / "static")]
    ):
        return None

    configured = tuple(finders.get_finders())
    if len(configured) != 2:
        return None
    filesystem, app_directories = configured
    if type(filesystem) is not finders.FileSystemFinder or type(app_directories) is not finders.AppDirectoriesFinder:
        return None
    return {
        "static_directory": str(Path(settings.STATICFILES_DIRS[0]).resolve()),
        "app_directories": [str(Path(storage.location).resolve()) for storage in app_directories.storages.values()],
        "language": settings.LANGUAGE_CODE,
    }


def read_static_asset_build(path: Path) -> str | None:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    sources = _asset_sources()
    key = metadata.get("key")
    if sources is not None and metadata.get("sources") == sources and isinstance(key, str) and re.fullmatch(r"assets-[0-9a-f]{64}", key):
        return key
    return None


@cache
def built_static_cache_key() -> str | None:
    # The build record and finder configuration are fixed for this process.
    return read_static_asset_build(STATIC_BUILD_FILE)


def write_static_asset_build(path: Path) -> None:
    from archivebox.core.staticfiles import admin_js_catalog

    sources = _asset_sources()
    if sources is None:
        raise RuntimeError("Cannot fingerprint static assets with nonstandard sources")

    files = {}
    for finder in finders.get_finders():
        for name, storage in finder.list([]):
            # Match Django's lookup order when two applications ship the same path.
            files.setdefault(name, Path(storage.path(name)))

    request = HttpRequest()
    request.method = "GET"
    catalog = admin_js_catalog(request, "").content
    digest = sha256()
    # Paths are relative to the versioned URL so a byte change in an imported
    # stylesheet, module, sprite or font invalidates the enclosing namespace.
    for name, source in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + sha256(source.read_bytes()).digest())
    digest.update(b"admin/jsi18n.js\0" + sha256(catalog).digest())
    path.write_text(json.dumps({"key": f"assets-{digest.hexdigest()}", "sources": sources}) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys

    import django

    django.setup()
    write_static_asset_build(Path(sys.argv[1]))
