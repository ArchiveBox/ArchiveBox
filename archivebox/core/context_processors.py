from pathlib import Path

from django.conf import settings

from archivebox.config import VERSION
from archivebox.config.version import get_COMMIT_HASH


def get_static_cache_key() -> str:
    """Version the admin stylesheet even when the checkout has uncommitted edits."""
    base_key = (get_COMMIT_HASH() or VERSION or "dev").strip()
    admin_css_path = Path(__file__).resolve().parent.parent / "templates" / "static" / "admin.css"
    try:
        return f"{base_key}-{admin_css_path.stat().st_mtime_ns}"
    except OSError:
        return base_key


def archivebox_globals(request):
    return {
        "VERSION": VERSION,
        "STATIC_CACHE_KEY": get_static_cache_key(),
        "password_reset_enabled": settings.ALLAUTH_ENABLED and bool(settings.EMAIL_HOST),
    }
