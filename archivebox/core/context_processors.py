from pathlib import Path

from django.core.cache import cache
from django.db.models import Sum

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
    context = {
        "VERSION": VERSION,
        "STATIC_CACHE_KEY": get_static_cache_key(),
    }
    if request.user.is_authenticated and request.user.is_staff:
        from archivebox.config import CONSTANTS
        from archivebox.core.models import Snapshot

        cache_key = f"navbar_archive_size:{CONSTANTS.DATA_DIR}"
        size = cache.get(cache_key)
        if size is None:
            size = Snapshot.objects.aggregate(total=Sum("output_size"))["total"] or 0
            cache.set(cache_key, size, timeout=3600)
        gb, tb = 1024**3, 1024**4
        if size >= tb:
            tenths = (size * 10 + tb - 1) // tb
            context["ARCHIVE_SIZE_ESTIMATE"] = f"{tenths // 10}.{tenths % 10} TB"
        else:
            context["ARCHIVE_SIZE_ESTIMATE"] = f"{(size + gb - 1) // gb} GB"
    return context
