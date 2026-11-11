from django.urls import path
from . import views

app_name = "feeds"
urlpatterns = [
    path("", views.index, name="index"),
    path("export/", views.export, name="export"),
    path("<int:feed_id>/revoke/", views.revoke, name="revoke"),
    path("read/<uuid:token>.rss", views.rss, name="rss"),
]
