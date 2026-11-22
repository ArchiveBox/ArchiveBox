from django.urls import path, re_path

from archivebox.base_models.admin import HexUUIDConverter

from . import views

app_name = "domains"
UUID = f"(?:{HexUUIDConverter.regex})"
urlpatterns = [
    path("", views.index, name="index"),
    path("site/", views.detail, name="site_detail"),
    path("site/replay-settings/", views.replay_settings, name="site_replay_settings"),
    re_path(rf"^(?P<clone_id>{UUID})/$", views.detail, name="detail"),
    re_path(rf"^(?P<clone_id>{UUID})/replay-settings/$", views.replay_settings, name="replay_settings"),
    re_path(rf"^(?P<clone_id>{UUID})/(?P<action>pause|resume)/$", views.action, name="action"),
]
