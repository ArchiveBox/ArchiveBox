from django.urls import path, re_path

from archivebox.base_models.admin import HexUUIDConverter

from . import actions, views

app_name = "domains"
UUID = f"(?:{HexUUIDConverter.regex})"
urlpatterns = [
    path("", views.index, name="index"),
    path("actions/", actions.site_actions, name="actions"),
    path("site/", views.detail, name="site_detail"),
    path("site/export/", views.export, name="site_export"),
    path("site/replay-settings/", views.replay_settings, name="site_replay_settings"),
    re_path(rf"^site/exports/(?P<process_id>{UUID})/cancel/$", views.cancel_export, name="site_cancel_export"),
    re_path(rf"^(?P<clone_id>{UUID})/$", views.detail, name="detail"),
    re_path(rf"^(?P<clone_id>{UUID})/exports/(?P<process_id>{UUID})/cancel/$", views.cancel_export, name="cancel_export"),
    re_path(rf"^(?P<clone_id>{UUID})/export/$", views.export, name="export"),
    re_path(rf"^(?P<clone_id>{UUID})/replay-settings/$", views.replay_settings, name="replay_settings"),
    re_path(rf"^(?P<clone_id>{UUID})/(?P<action>pause|resume)/$", views.action, name="action"),
]
