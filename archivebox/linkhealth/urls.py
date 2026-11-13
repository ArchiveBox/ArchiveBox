from django.urls import path, re_path
from . import views

app_name = "linkhealth"
urlpatterns = [
    path("", views.index, name="index"),
    path("scan/", views.scan, name="scan"),
    re_path(r"^(?P<process_id>[0-9a-f]{32})/cancel/$", views.cancel, name="cancel"),
]
