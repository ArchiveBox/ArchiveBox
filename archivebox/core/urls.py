from django.contrib import admin

from django.urls import path, include
from django.views import static
from django.conf import settings
from django.contrib.staticfiles import views
from django.views.generic.base import RedirectView

from core.views import MainIndex, AddLinks, LinkDetails

admin.site.site_header = 'ArchiveBox'
admin.site.index_title = 'Links' 
admin.site.site_title = 'Index'


urlpatterns = [
    path('robots.txt', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'robots.txt'}),
    path('favicon.ico', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'favicon.ico'}),

    path('archive/', RedirectView.as_view(url='/')),
    path('archive/<path:path>', LinkDetails.as_view(), name='LinkAssets'),
    path('add/', AddLinks.as_view(), name='AddLinks'),
    
    path('static/<path>', views.serve),
    
    path('accounts/login/', RedirectView.as_view(url='/admin/login/')),
    path('accounts/logout/', RedirectView.as_view(url='/admin/logout/')),

    path('admin/core/snapshot/add/', RedirectView.as_view(url='/add/')),

    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    
    path('old.html', MainIndex.as_view(), name='OldHome'),
    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('', RedirectView.as_view(url='/admin/core/snapshot/'), name='Home'),
]
