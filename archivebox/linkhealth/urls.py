from django.urls import path, re_path

from . import views

app_name = "linkhealth"
urlpatterns = [
    path("", views.index, name="index"),
    path("scan/", views.scan, name="scan"),
    path("recheck/", views.recheck_selected, name="recheck_selected"),
    re_path(r"^(?P<snapshot_id>[0-9a-fA-F]{32})/retry/$", views.retry, name="retry"),
]
