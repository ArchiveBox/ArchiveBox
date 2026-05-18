__package__ = "archivebox.api"

from urllib.parse import quote

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import path
from django.views.generic.base import RedirectView

from archivebox.core.host_utils import build_web_url

from .v1_api import urls as v1_api_urls


def archive_redirect_view(request: HttpRequest, url: str) -> HttpResponseRedirect:
    if request.META.get("QUERY_STRING"):
        url = f"{url}?{request.META['QUERY_STRING']}"
    return redirect(build_web_url(f"/web/{quote(url, safe=':/')}", request=request))


urlpatterns = [
    path("", RedirectView.as_view(url="/api/v1/docs")),
    path("archive/<path:url>", archive_redirect_view, name="api-archive-redirect"),
    path("v1/", RedirectView.as_view(url="/api/v1/docs")),
    path("v1/", v1_api_urls),
    path("v1", RedirectView.as_view(url="/api/v1/docs")),
    # ... v2 can be added here ...
    # path("v2/",              v2_api_urls),
    # path("v2",               RedirectView.as_view(url='/api/v2/docs')),
]
