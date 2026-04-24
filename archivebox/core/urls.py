__package__ = "archivebox.core"

from django.urls import path, re_path, include
from django.views import static
from django.conf import settings
from django.views.generic.base import RedirectView
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render

from archivebox.misc.serve_static import serve_static

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.views import (
    HomepageView,
    SnapshotView,
    SnapshotPathView,
    SnapshotReplayView,
    OriginalDomainReplayView,
    PublicIndexView,
    AddView,
    WebAddView,
    HealthCheckView,
    live_progress_view,
)


def is_api_request(request: HttpRequest) -> bool:
    return request.path.startswith('/api/')


def bad_request(request: HttpRequest, exception=None):
    if is_api_request(request):
        return JsonResponse({
            "error": "Bad Request",
            "status_code": 400,
            "message": str(exception) if exception else "The request could not be understood.",
            "detail": "Please check your request parameters and try again.",
        }, status=400)
    
    context = {
        "error_message": str(exception) if exception else "The request could not be understood.",
        "title": "400 - Bad Request",
    }
    return render(request, 'core/400.html', context=context, status=400)


def permission_denied(request: HttpRequest, exception=None):
    if is_api_request(request):
        return JsonResponse({
            "error": "Permission Denied",
            "status_code": 403,
            "message": str(exception) if exception else "You do not have permission to access this resource.",
        }, status=403)
    
    context = {
        "error_message": str(exception) if exception else "You do not have permission to access this resource.",
        "title": "403 - Forbidden",
    }
    return render(request, 'core/400.html', context=context, status=403)


def page_not_found(request: HttpRequest, exception=None):
    if is_api_request(request):
        return JsonResponse({
            "error": "Not Found",
            "status_code": 404,
            "message": str(exception) if exception else "The requested resource could not be found.",
        }, status=404)
    
    context = {
        "error_message": str(exception) if exception else "The requested page could not be found.",
        "title": "404 - Not Found",
    }
    return render(request, 'core/400.html', context=context, status=404)


def server_error(request: HttpRequest):
    if is_api_request(request):
        return JsonResponse({
            "error": "Server Error",
            "status_code": 500,
            "message": "An unexpected error occurred on the server.",
        }, status=500)
    
    context = {
        "error_message": "An unexpected error occurred on the server. Please try again later.",
        "title": "500 - Server Error",
    }
    return render(request, 'core/400.html', context=context, status=500)


handler400 = 'archivebox.core.urls.bad_request'
handler403 = 'archivebox.core.urls.permission_denied'
handler404 = 'archivebox.core.urls.page_not_found'
handler500 = 'archivebox.core.urls.server_error'


# GLOBAL_CONTEXT doesn't work as-is, disabled for now: https://github.com/ArchiveBox/ArchiveBox/discussions/1306
# from archivebox.config import VERSION, VERSIONS_AVAILABLE, CAN_UPGRADE
# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': VERSIONS_AVAILABLE, 'CAN_UPGRADE': CAN_UPGRADE}


# print('DEBUG', settings.DEBUG)

urlpatterns = [
    re_path(r"^static/(?P<path>.*)$", serve_static),
    # re_path(r"^media/(?P<path>.*)$", static.serve, {"document_root": settings.MEDIA_ROOT}),
    path("robots.txt", static.serve, {"document_root": settings.STATICFILES_DIRS[0], "path": "robots.txt"}),
    path("favicon.ico", static.serve, {"document_root": settings.STATICFILES_DIRS[0], "path": "favicon.ico"}),
    path("docs/", RedirectView.as_view(url="https://github.com/ArchiveBox/ArchiveBox/wiki"), name="Docs"),
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
    path("add/", AddView.as_view(), name="add"),
    path("accounts/login/", RedirectView.as_view(url="/admin/login/")),
    path("accounts/logout/", RedirectView.as_view(url="/admin/logout/")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("admin/live-progress/", live_progress_view, name="live_progress"),
    path("admin/", archivebox_admin.urls),
    path("api/", include("archivebox.api.urls"), name="api"),
    path("health/", HealthCheckView.as_view(), name="healthcheck"),
    path("error/", lambda request: _raise_test_error(request)),
    # path('jet_api/', include('jet_django.urls')),  Enable to use https://www.jetadmin.io/integrations/django
    path("index.html", RedirectView.as_view(url="/")),
    path("", HomepageView.as_view(), name="Home"),
]


def _raise_test_error(_request: HttpRequest):
    raise ZeroDivisionError("Intentional test error route")


if settings.DEBUG_TOOLBAR:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

if settings.DEBUG_REQUESTS_TRACKER:
    urlpatterns += [path("__requests_tracker__/", include("requests_tracker.urls"))]


# # Proposed FUTURE URLs spec
# path('',                 HomepageView)
# path('/add',             AddView)
# path('/public',          PublicIndexView)
# path('/snapshot/:slug',  SnapshotView)

# path('/admin',           admin.site.urls)
# path('/accounts',        django.contrib.auth.urls)

# # Proposed REST API spec
# # :slugs can be uuid, short_uuid, or any of the unique index_fields
# path('api/v1/'),
# path('api/v1/core/'                      [GET])
# path('api/v1/core/snapshot/',            [GET, POST, PUT]),
# path('api/v1/core/snapshot/:slug',       [GET, PATCH, DELETE]),
# path('api/v1/core/archiveresult',        [GET, POST, PUT]),
# path('api/v1/core/archiveresult/:slug',  [GET, PATCH, DELETE]),
# path('api/v1/core/tag/',                 [GET, POST, PUT]),
# path('api/v1/core/tag/:slug',            [GET, PATCH, DELETE]),

# path('api/v1/cli/',                      [GET])
# path('api/v1/cli/{add,list,config,...}', [POST]),  # pass query as kwargs directly to `run_subcommand` and return stdout, stderr, exitcode

# path('api/v1/extractors/',                    [GET])
# path('api/v1/extractors/:extractor/',         [GET]),
# path('api/v1/extractors/:extractor/:func',    [GET, POST]),  # pass query as args directly to chosen function

# future, just an idea:
# path('api/v1/scheduler/',                [GET])
# path('api/v1/scheduler/task/',           [GET, POST, PUT]),
# path('api/v1/scheduler/task/:slug',      [GET, PATCH, DELETE]),
