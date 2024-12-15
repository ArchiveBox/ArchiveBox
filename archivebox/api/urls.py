__package__ = 'archivebox.api'

from django.urls import path
from django.views.generic.base import RedirectView

from .v1_api import urls as v1_api_urls

urlpatterns = [
    path("",                 RedirectView.as_view(url='/api/v1')),

    path("v1/",              v1_api_urls),
    path("v1",               RedirectView.as_view(url='/api/v1/docs')),

    # ... v2 can be added here ...
    # path("v2/",              v2_api_urls),
    # path("v2",               RedirectView.as_view(url='/api/v2/docs')),
]
