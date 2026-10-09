from django.urls import path, re_path

from . import views

app_name = "importers"
UUID = r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
urlpatterns = [
    path("", views.index, name="index"),
    path("custom/", views.create_custom, name="custom"),
    path("new/<slug:plugin>/<slug:feed>/", views.configure, name="new"),
    path("guide/<slug:plugin>/<slug:feed>/<int:step>/", views.guide_image, name="guide-image"),
    path("icon/<slug:plugin>/<slug:feed>/", views.brand_icon, name="icon"),
    re_path(rf"^runs/(?P<run_id>{UUID})/$", views.run_detail, name="run"),
    re_path(rf"^runs/(?P<run_id>{UUID})/items\.json$", views.run_json, name="run-json"),
    re_path(rf"^(?P<source_id>{UUID})/$", views.detail, name="detail"),
    re_path(rf"^(?P<source_id>{UUID})/edit/$", views.configure, name="edit"),
    re_path(rf"^(?P<source_id>{UUID})/(?P<action>[a-z]+)/$", views.action, name="action"),
]
