from django.urls import path, re_path

from archivebox.opencode.views import agent_health_view, agent_view, opencode_proxy_view


urlpatterns = [
    path("", agent_view, name="opencode-agent"),
    path("opencode/_archivebox/health", agent_health_view, name="opencode-health"),
    re_path(
        r"^opencode(?:/(?P<path>.*))?$",
        opencode_proxy_view,
        name="opencode-proxy",
    ),
]
