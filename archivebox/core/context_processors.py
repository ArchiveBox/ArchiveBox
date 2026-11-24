from pathlib import Path

from django.conf import settings

from archivebox.config import VERSION
from archivebox.config.version import get_COMMIT_HASH


ADMIN_STYLESHEET = Path(__file__).resolve().parent.parent / "templates" / "static" / "admin.css"


def get_static_cache_key() -> str:
    """Version the static asset tree for this build."""
    base_key = (get_COMMIT_HASH() or VERSION or "dev").strip()
    try:
        return f"{base_key}-{ADMIN_STYLESHEET.stat().st_mtime_ns}"
    except OSError:
        return base_key


def archivebox_globals(request):
    from archivebox.machine.models import Machine

    return {
        "VERSION": VERSION,
        "STATIC_CACHE_KEY": get_static_cache_key(),
        "password_reset_enabled": settings.ALLAUTH_ENABLED and bool(settings.EMAIL_HOST),
        "current_machine": Machine.current_readonly() if getattr(getattr(request, "user", None), "is_superuser", False) else None,
    }
