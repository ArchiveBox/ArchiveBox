from django.contrib import admin

from django.urls import path, include
from django.views import static
from django.conf import settings
from django.views.generic.base import RedirectView

from core.views import MainIndex, OldIndex, LinkDetails, PublicArchiveView, SearchResultsView, add_view


# print('DEBUG', settings.DEBUG)

urlpatterns = [
    path('robots.txt', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'robots.txt'}),
    path('favicon.ico', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'favicon.ico'}),

    path('docs/', RedirectView.as_view(url='https://github.com/pirate/ArchiveBox/wiki'), name='Docs'),

    path('archive/', RedirectView.as_view(url='/')),
    path('archive/<path:path>', LinkDetails.as_view(), name='LinkAssets'),
    path('add/', add_view),
    
    path('accounts/login/', RedirectView.as_view(url='/admin/login/')),
    path('accounts/logout/', RedirectView.as_view(url='/admin/logout/')),


    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    
    path('old.html', OldIndex.as_view(), name='OldHome'),
    path('index.html', RedirectView.as_view(url='/')),
    path('index.json', static.serve, {'document_root': settings.OUTPUT_DIR, 'path': 'index.json'}),
    path('', MainIndex.as_view(), name='Home'),
    path('public/', PublicArchiveView.as_view(), name='public-index'),
    path('search_results/', SearchResultsView.as_view(), name='search-results'),
]
