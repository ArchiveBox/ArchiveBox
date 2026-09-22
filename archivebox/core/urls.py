__package__ = "archivebox.core"

from importlib.util import find_spec

from django.conf import settings
from django.urls import path, re_path, include
from django.views import static
from django.views.generic.base import RedirectView
from django.http import HttpRequest

from archivebox.config.constants import CONSTANTS
from archivebox.misc.serve_static import serve_static

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.views import (
    HomepageView,
    SnapshotView,
    SnapshotPathView,
    SnapshotReplayView,
    SnapshotReplayAuthView,
    OriginalDomainReplayView,
    PublicIndexView,
    AddView,
    WebAddView,
    HealthCheckView,
)
from archivebox.progressmonitor.views import live_progress_view
from archivebox.search.views import public_snapshot_search_stream_view
from archivebox.opencode.views import opencode_proxy_view

urlpatterns = [
    re_path(r"^static/(?P<path>.*)$", serve_static),
    path("robots.txt", static.serve, {"document_root": CONSTANTS.STATIC_DIR, "path": "robots.txt"}),
    path("favicon.ico", static.serve, {"document_root": CONSTANTS.STATIC_DIR, "path": "favicon.ico"}),
    path("docs/", RedirectView.as_view(url="https://github.com/ArchiveBox/ArchiveBox/wiki"), name="Docs"),
    re_path(r"^admin/agent/?(?=$|opencode)", include("archivebox.opencode.urls")),
    re_path(r"^(?P<path>assets/.*)$", opencode_proxy_view, name="opencode-assets"),
    path("public/search-stream/", public_snapshot_search_stream_view, name="public-search-stream"),
    path("public/", PublicIndexView.as_view(), name="public-index"),
    path("public.html", RedirectView.as_view(url="/public/"), name="public-index-html"),
    path("archive/", RedirectView.as_view(url="/")),
    path("archive/<path:path>", SnapshotView.as_view(), name="Snapshot"),
    re_path(r"^snapshot\/(?P<snapshot_id>[0-9a-fA-F-]{8,36})(?:\/(?P<path>.*))?$", SnapshotReplayView.as_view(), name="snapshot-replay"),
    re_path(r"^original\/(?P<domain>[^/]+)(?:\/(?P<path>.*))?$", OriginalDomainReplayView.as_view(), name="original-replay"),
    re_path(r"^web/(?P<url>(?!\d{4}(?:\d{2})?(?:\d{2})?(?:/|$)).+)$", WebAddView.as_view(), name="web-add"),
    re_path(
        r"^(?P<username>[^/]+)/(?P<date>\d{4}(?:\d{2})?(?:\d{2})?)/(?P<url>https?://.*)$",
        SnapshotPathView.as_view(),
        name="snapshot-path-url",
    ),
    re_path(
        r"^(?P<username>[^/]+)/(?P<date>\d{4}(?:\d{2})?(?:\d{2})?)/(?P<domain>[^/]+)(?:/(?P<snapshot_id>[0-9a-fA-F-]{8,36})(?:/(?P<path>.*))?)?$",
        SnapshotPathView.as_view(),
        name="snapshot-path",
    ),
    re_path(r"^(?P<username>[^/]+)/(?P<url>https?://.*)$", SnapshotPathView.as_view(), name="snapshot-path-url-nodate"),
    re_path(
        r"^(?P<username>[^/]+)/(?P<domain>[^/]+)(?:/(?P<snapshot_id>[0-9a-fA-F-]{8,36})(?:/(?P<path>.*))?)?$",
        SnapshotPathView.as_view(),
        name="snapshot-path-nodate",
    ),
    path("admin/core/snapshot/add/", RedirectView.as_view(url="/add/")),
    path("admin/core/snapshot/replay-auth/", SnapshotReplayAuthView.as_view(), name="snapshot-replay-auth"),
    path("add/", AddView.as_view(), name="add"),
    # ``query_string=True`` preserves the ``?next=…`` param that Django's
    # auth/login mixins append, so e.g. ``UserPassesTestMixin`` redirecting
    # an unauthenticated ``/add`` visitor to ``/accounts/login/?next=/add/``
    # carries the ``next`` through to ``/admin/login/`` and lands them at
    # ``/add/`` after login instead of the admin homepage.
    path("accounts/login/", RedirectView.as_view(url="/admin/login/", query_string=True)),
    path("accounts/logout/", RedirectView.as_view(url="/admin/logout/", query_string=True)),
    path("accounts/", include("django.contrib.auth.urls")),
    path("progress.json", live_progress_view, name="live_progress"),
    path("admin/", archivebox_admin.urls),
    path("api/", include("archivebox.api.urls"), name="api"),
    path("health/", HealthCheckView.as_view(), name="healthcheck"),
    path("error/", lambda request: _raise_test_error(request)),
    path("index.html", RedirectView.as_view(url="/")),
    path("", HomepageView.as_view(), name="Home"),
]


def _raise_test_error(_request: HttpRequest):
    raise ZeroDivisionError("Intentional test error route")


if getattr(settings, "DEBUG_TOOLBAR", False):
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

if getattr(settings, "DEBUG_REQUESTS_TRACKER", False) and find_spec("requests_tracker"):
    urlpatterns += [path("__requests_tracker__/", include("requests_tracker.urls"))]
