from django.contrib import admin

from django.urls import path, include
from django.views import static
from django.conf import settings
from django.contrib.staticfiles import views
from django.views.generic.base import RedirectView

from core.views import MainIndex, AddLinks, LinkDetails

admin.site.site_header = 'ArchiveBox Admin'
admin.site.index_title = 'Archive Administration'

urlpatterns = [
    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('robots.txt', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'robots.txt'}),
    path('favicon.ico', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'favicon.ico'}),

    path('archive/', RedirectView.as_view(url='/')),
    path('archive/<path:path>', LinkDetails.as_view(), name='LinkAssets'),
    path('add/', AddLinks.as_view(), name='AddLinks'),
    
    path('static/<path>', views.serve),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    path('', MainIndex.as_view(), name='Home'),
]


