__package__ = 'archivebox.core'

from django.urls import path, include
from django.views import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from django.views.generic.base import RedirectView

from .admin import archivebox_admin
from .views import HomepageView, SnapshotView, PublicIndexView, AddView, HealthCheckView


# GLOBAL_CONTEXT doesn't work as-is, disabled for now: https://github.com/ArchiveBox/ArchiveBox/discussions/1306
# from config import VERSION, VERSIONS_AVAILABLE, CAN_UPGRADE
# GLOBAL_CONTEXT = {'VERSION': VERSION, 'VERSIONS_AVAILABLE': VERSIONS_AVAILABLE, 'CAN_UPGRADE': CAN_UPGRADE}


# print('DEBUG', settings.DEBUG)

urlpatterns = [
    path('public/', PublicIndexView.as_view(), name='public-index'),

    path('robots.txt', static.serve, {'document_root': settings.STATICFILES_DIRS[0], 'path': 'robots.txt'}),
    path('favicon.ico', static.serve, {'document_root': settings.STATICFILES_DIRS[0], 'path': 'favicon.ico'}),

    path('docs/', RedirectView.as_view(url='https://github.com/ArchiveBox/ArchiveBox/wiki'), name='Docs'),

    path('archive/', RedirectView.as_view(url='/')),
    path('archive/<path:path>', SnapshotView.as_view(), name='Snapshot'),

    path('admin/core/snapshot/add/', RedirectView.as_view(url='/add/')),
    path('add/', AddView.as_view(), name='add'),

    path('accounts/login/', RedirectView.as_view(url='/admin/login/')),
    path('accounts/logout/', RedirectView.as_view(url='/admin/logout/')),


    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', archivebox_admin.urls),
    
    path("api/",      include('api.urls')),

    path('health/', HealthCheckView.as_view(), name='healthcheck'),
    path('error/', lambda *_: 1/0),

    # path('jet_api/', include('jet_django.urls')),  Enable to use https://www.jetadmin.io/integrations/django

    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('', HomepageView.as_view(), name='Home'),
]
urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG_TOOLBAR:
    urlpatterns += [path('__debug__/', include("debug_toolbar.urls"))]

if settings.DEBUG_REQUESTS_TRACKER:
    urlpatterns += [path("__requests_tracker__/", include("requests_tracker.urls"))]


# # Proposed FUTURE URLs spec
# path('',                 HomepageView)
# path('/add',             AddView)
# path('/public',          PublicIndexView)
# path('/snapshot/:slug',  SnapshotView)

# path('/admin',           admin.site.urls)
# path('/accounts',        django.contrib.auth.urls)

# # Prposed REST API spec
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
