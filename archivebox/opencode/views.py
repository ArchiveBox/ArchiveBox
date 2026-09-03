"""Django adapter for the optional plugin; never import its runtime at startup."""

import logging
from io import BytesIO

from asgiref.sync import sync_to_async

from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.views import redirect_to_login
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.core.handlers.asgi import ASGIRequest
from django.db import close_old_connections
from django.http import Http404, HttpResponse, HttpResponseForbidden, StreamingHttpResponse
from django.template import engines
from django.urls import Resolver404, resolve
from django.views.decorators.csrf import csrf_exempt

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config, get_request_config
from archivebox.core.routes_util import build_admin_url, get_admin_host, get_api_base_url, get_base_url, host_matches
from archivebox.plugins.discovery import get_plugin_template

_LOGGER = logging.getLogger(__name__)


def _runtime_settings(request, config):
    from abx_plugins.plugins.opencode import runtime

    settings = runtime._settings(config, CONSTANTS.DATA_DIR)
    route_config = request.__dict__.get("archivebox_config")
    settings.update(
        archivebox_base_url=get_base_url(request=request, config=route_config).rstrip("/"),
        archivebox_admin_url=build_admin_url("/admin/", request=request, config=route_config).rstrip("/"),
        archivebox_api_url=f"{get_api_base_url(request=request, config=route_config).rstrip('/')}/api/",
    )
    return runtime, settings


def _dispatch(request, path=None):
    try:
        config = dict(get_config().model_dump(mode="json"))
        if not config.get("OPENCODE_ENABLED", False):
            raise Http404
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            return HttpResponseForbidden("Agent access requires a superuser account.")

        runtime, settings = _runtime_settings(request, config)
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


def _websocket_context(scope):
    close_old_connections()
    try:
        match = resolve(scope["path"])
        if match.url_name != "opencode-proxy":
            raise PermissionDenied
        request = ASGIRequest(
            {**scope, "type": "http", "method": "GET", "scheme": "https" if scope.get("scheme") == "wss" else "http"},
            BytesIO(),
        )
        route_config = get_request_config(request, resolve_plugins=False)
        request.archivebox_config = route_config
        if (
            route_config.USES_SUBDOMAIN_ROUTING
            and route_config.BASE_URL
            and not host_matches(request.get_host(), get_admin_host(config=route_config, request=request))
        ):
            raise PermissionDenied
        SessionMiddleware(_dispatch).process_request(request)
        AuthenticationMiddleware(_dispatch).process_request(request)
        config = get_config().model_dump(mode="json")
        if not config.get("OPENCODE_ENABLED") or not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        runtime, settings = _runtime_settings(request, config)
        if not request.headers.get("Origin") or not runtime._origin_allowed("POST", request.get_host(), request.headers):
            raise PermissionDenied
        return runtime, settings, match.kwargs.get("path", "")
    finally:
        close_old_connections()


async def websocket_view(scope, receive, send):
    if (await receive())["type"] != "websocket.connect":
        return
    try:
        runtime, settings, path = await sync_to_async(_websocket_context)(scope)
        await runtime.websocket_proxy(settings, path, scope.get("query_string", b""), scope.get("subprotocols", []), receive, send)
    except (PermissionDenied, Resolver404, Http404):
        await send({"type": "websocket.close", "code": 1008})
    except Exception:
        _LOGGER.exception("Optional AI WebSocket failed")
        await send({"type": "websocket.close", "code": 1011})
