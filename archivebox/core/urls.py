from django.contrib import admin

from django.urls import path, include
from django.views import static
from django.conf import settings
from django.views.generic.base import RedirectView

from core.views import MainIndex, OldIndex, LinkDetails


# print('DEBUG', settings.DEBUG)

urlpatterns = [
    path('robots.txt', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'robots.txt'}),
    path('favicon.ico', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'favicon.ico'}),

    path('docs/', RedirectView.as_view(url='https://github.com/pirate/ArchiveBox/wiki'), name='Docs'),

    path('archive/', RedirectView.as_view(url='/')),
    path('archive/<path:path>', LinkDetails.as_view(), name='LinkAssets'),
    path('add/', RedirectView.as_view(url='/admin/core/snapshot/add/')),
    
    path('accounts/login/', RedirectView.as_view(url='/admin/login/')),
    path('accounts/logout/', RedirectView.as_view(url='/admin/logout/')),


    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    
    path('old.html', OldIndex.as_view(), name='OldHome'),
    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('', MainIndex.as_view(), name='Home'),
]
