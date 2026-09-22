from django.urls import path, re_path

from archivebox.opencode.views import agent_view, opencode_proxy_view


urlpatterns = [
    path("", agent_view, name="opencode-agent"),
    re_path(
        r"^opencode(?:/(?P<path>.*))?$",
        opencode_proxy_view,
        name="opencode-proxy",
    ),
]
