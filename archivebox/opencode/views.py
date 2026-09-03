"""Django adapter for the optional plugin; never import its runtime at startup."""

import logging

from django.http import Http404, HttpResponse, HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import redirect
from django.template import engines
from django.views.decorators.csrf import csrf_exempt

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.core.routes_util import build_admin_url, get_api_base_url, get_base_url
from archivebox.plugins.discovery import get_plugin_template

_LOGGER = logging.getLogger(__name__)


def _dispatch(request, path=None):
    try:
        config = dict(get_config().model_dump(mode="json"))
        if not config.get("OPENCODE_ENABLED", False):
            raise Http404
        if not request.user.is_authenticated:
            return redirect(f"/admin/login/?next={request.get_full_path()}")
        if not request.user.is_active or not request.user.is_superuser:
            return HttpResponseForbidden("Agent access requires a superuser account.")

        from abx_plugins.plugins.opencode import runtime

        settings = runtime._settings(config, CONSTANTS.DATA_DIR)
        route_config = request.__dict__.get("archivebox_config")
        settings.update(
            archivebox_base_url=get_base_url(request=request, config=route_config).rstrip("/"),
            archivebox_admin_url=build_admin_url("/admin/", request=request, config=route_config).rstrip("/"),
            archivebox_api_url=f"{get_api_base_url(request=request, config=route_config).rstrip('/')}/api/",
        )
        if path is None:
            from archivebox.core.admin_site import archivebox_admin

            context = {**archivebox_admin.each_context(request), **runtime.agent_context(settings)}
            source = get_plugin_template("opencode", "agent", fallback=False)
            if source is None:
                raise RuntimeError("Agent template unavailable")
            return HttpResponse(engines["django"].from_string(source).render(context, request))

        if not runtime._origin_allowed(request.method, request.get_host(), request.headers):
            return HttpResponseForbidden("Cross-origin agent requests are blocked.")
        status, headers, body = runtime.proxy(
            settings,
            request.method,
            path,
            tuple((key, value) for key, values in request.GET.lists() for value in values),
            request.headers,
            request.body,
        )
        response_type = HttpResponse if isinstance(body, bytes) else StreamingHttpResponse
        response = response_type(body, status=status, headers=headers)
        response.xframe_options_exempt = True
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response
    except Http404:
        raise
    except Exception:
        # Optional-service boundary, including imports and template rendering.
        _LOGGER.exception("Optional AI service failed")
        return HttpResponse("AI service unavailable. See server logs.", status=503, content_type="text/plain")


def agent_view(request):
    return _dispatch(request)


@csrf_exempt
def opencode_proxy_view(request, path=None):
    return _dispatch(request, path=path or "")
