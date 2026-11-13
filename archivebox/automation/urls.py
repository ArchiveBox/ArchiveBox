from django.urls import path, re_path

from archivebox.base_models.admin import HexUUIDConverter

from . import views

app_name = "automation"
UUID = f"(?:{HexUUIDConverter.regex})"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.edit, name="new"),
    path("history/", views.history, name="history"),
    re_path(rf"^(?P<rule_id>{UUID})/$", views.edit, name="edit"),
    re_path(rf"^(?P<rule_id>{UUID})/preview/$", views.preview, name="preview"),
    re_path(rf"^(?P<rule_id>{UUID})/toggle/$", views.toggle, name="toggle"),
]
