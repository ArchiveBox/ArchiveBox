from django.urls import path
from . import views

app_name = "storageaudit"
urlpatterns = [
    path("", views.index, name="index"),
    path("scan/", views.scan, name="scan"),
    path("preview/", views.preview, name="preview"),
    path("apply/", views.apply, name="apply"),
]
