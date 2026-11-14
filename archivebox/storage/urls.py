from django.urls import path
from . import views

app_name = "storage"
urlpatterns = [
    path("", views.index, name="index"),
    path("configure/", views.configure, name="configure"),
    path("oauth/callback/", views.oauth_callback, name="oauth-callback"),
    path("connect/", views.oauth_start, name="oauth-start"),
    path("<str:action>/", views.action, name="action"),
]
