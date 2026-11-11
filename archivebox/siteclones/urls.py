from django.urls import path, re_path

from . import views

app_name = "siteclones"
UUID = r"[0-9a-fA-F-]{32,36}"
urlpatterns = [
    path("", views.index, name="index"),
    re_path(rf"^(?P<clone_id>{UUID})/$", views.detail, name="detail"),
    re_path(rf"^(?P<clone_id>{UUID})/(?P<action>pause|resume)/$", views.action, name="action"),
]
