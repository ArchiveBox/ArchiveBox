from django.urls import path

from . import views

app_name = "storage"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.configure, name="new"),
    path("oauth/callback/", views.oauth_callback, name="oauth-callback"),
    path("<str:destination_id>/", views.detail, name="detail"),
    path("<str:destination_id>/edit/", views.configure, name="edit"),
    path("<str:destination_id>/connect/", views.oauth_start, name="oauth-start"),
    path("<str:destination_id>/<str:action>/", views.action, name="action"),
]
