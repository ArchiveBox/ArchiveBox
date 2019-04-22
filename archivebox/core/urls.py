from django.contrib import admin
from django.urls import path


from core.views import MainIndex, LinkDetails

urlpatterns = [
    path('admin/', admin.site.urls),
    path('archive/<timestamp>/', LinkDetails.as_view(), name='LinkDetails'),
    path('main/', MainIndex.as_view(), name='Home'),
]
