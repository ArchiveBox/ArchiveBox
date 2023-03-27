from django.contrib import admin

from django.urls import path, include
from django.views import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from django.views.generic.base import RedirectView
from core.views import HomepageView, SnapshotView, PublicIndexView, AddView, HealthCheckView
from archivebox.core.views import CSVUploadView

urlpatterns = [
    path('csv-upload/', CSVUploadView.as_view(), name='csv_upload'),
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
    path('admin/', admin.site.urls),

    path('health/', HealthCheckView.as_view(), name='healthcheck'),

    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('', HomepageView.as_view(), name='Home'),
]
urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG_TOOLBAR:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]

