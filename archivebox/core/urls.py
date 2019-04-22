from django.contrib import admin
from django.utils.translation import ugettext_lazy

from django.urls import path, include
from django.conf import settings

from core.views import MainIndex, AddLinks, LinkDetails

admin.site.site_header = 'ArchiveBox Admin'
admin.site.index_title = 'Archive Administration'

urlpatterns = [
    path('archive/<timestamp>/', LinkDetails.as_view(), name='LinkDetails'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    path('add/', AddLinks.as_view(), name='AddLinks'),
    path('', MainIndex.as_view(), name='Home'),
]


if settings.SERVE_STATIC:
    # serve staticfiles via runserver
    from django.contrib.staticfiles import views
    urlpatterns += [
        path('static/<path>', views.serve),
    ]
