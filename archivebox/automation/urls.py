from django.urls import path

from . import views

app_name = "automation"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.edit, name="new"),
    path("history/", views.history, name="history"),
    path("<int:rule_id>/", views.edit, name="edit"),
    path("<int:rule_id>/preview/", views.preview, name="preview"),
    path("<int:rule_id>/toggle/", views.toggle, name="toggle"),
]
