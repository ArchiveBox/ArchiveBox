from django.urls import path, re_path

from archivebox.base_models.admin import HexUUIDConverter

from . import webhook_views as views

app_name = "webhooks"
urlpatterns = [
    path("", views.index, name="index"),
    path("data/", views.data, name="data"),
    path("save/", views.save, name="save"),
    path("preview/", views.preview, name="preview"),
    re_path(rf"^(?P<webhook_id>{HexUUIDConverter.regex})/delete/$", views.delete, name="delete"),
]
