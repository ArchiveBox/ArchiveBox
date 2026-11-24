from django.conf import settings
from django.contrib.staticfiles.storage import StaticFilesStorage
from django.http import Http404, HttpResponse
from django.utils.cache import get_conditional_response, set_response_etag
from django.views.decorators.http import require_safe
from django.views.i18n import JavaScriptCatalog

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
def admin_js_catalog(request, version):
    # The fixed English catalog only depends on the deployed Django code and
    # formats. Use Django's generator so its JS contract follows the installed version.
    response = JavaScriptCatalog.as_view(packages=["django.contrib.admin"])(request)
    immutable = version == get_static_cache_key() and not request.GET and not settings.DEBUG
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "public, no-cache"
    set_response_etag(response)
    return get_conditional_response(request, etag=response.headers["ETag"], response=response)


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
