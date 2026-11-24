from django.conf import settings
from django.contrib.staticfiles.storage import StaticFilesStorage
from django.http import Http404, HttpResponse
from django.utils.cache import get_conditional_response
from django.views.decorators.http import require_safe

from archivebox.core.context_processors import get_static_cache_key


class VersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        if url.startswith(settings.STATIC_URL):
            # A directory prefix also versions relative CSS imports, fonts,
            # icon sprites, and JavaScript module imports.
            path = url.removeprefix(settings.STATIC_URL)
            return f"{settings.STATIC_URL}v/{get_static_cache_key()}/{path}"
        return url


@require_safe
def plugin_icon(request, plugin, fingerprint):
    from archivebox.plugins.discovery import get_plugin_icon_asset

    asset = get_plugin_icon_asset(plugin)
    if asset is None or asset[0] != fingerprint:
        raise Http404
    etag = f'"{fingerprint}"'
    response = get_conditional_response(request, etag=etag)
    if response is None:
        response = HttpResponse(asset[1], content_type="image/svg+xml")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
