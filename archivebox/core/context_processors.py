from pathlib import Path

from django.conf import settings

from archivebox.config import VERSION
from archivebox.config.version import IN_DOCKER, get_COMMIT_HASH
from archivebox.core.static_asset_build import built_static_cache_key


ADMIN_STYLESHEET = Path(__file__).resolve().parent.parent / "templates" / "static" / "admin.css"


def get_static_cache_key() -> str:
    """Version the static asset tree for this build."""
    commit = get_COMMIT_HASH()
    if IN_DOCKER and not settings.DEBUG:
        # Older images and runtime overrides keep their release-scoped URLs.
        if key := built_static_cache_key() or commit:
            return key
    base_key = (commit or VERSION or "dev").strip()
    try:
        return f"{base_key}-{ADMIN_STYLESHEET.stat().st_mtime_ns}"
    except OSError:
        return base_key


def archivebox_globals(request):
    from archivebox.config.common import get_request_config

    machine = None
    if getattr(getattr(request, "user", None), "is_superuser", False):
        get_request_config(request)
        machine = request._archivebox_config_machine
    return {
        "VERSION": VERSION,
        "STATIC_CACHE_KEY": get_static_cache_key(),
        "password_reset_enabled": settings.ALLAUTH_ENABLED and bool(settings.EMAIL_HOST),
        "current_machine": machine,
    }
