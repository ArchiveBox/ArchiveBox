"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from django.core.handlers.asgi import ASGIHandler
from django.conf import settings

from archivebox.config.django import setup_django
from archivebox.core.replay_admission import ReplayAdmission
from archivebox.core.replay_timing import ReplayPhaseObserver
from archivebox.workers.request_activity import RequestActivityObserver, bind_request_activity
from archivebox.plugins.discovery import wrap_plugin_asgi

setup_django(check_db=True)


class ArchiveBoxASGIHandler(ASGIHandler):
    async def handle(self, scope, receive, send):
        close = None

        def own(closer):
            nonlocal close
            if close is not None:
                raise RuntimeError("An upstream already owns this request's response stream")
            close = closer

        # Optional private capability for a host plugin streaming an upstream
        # response. Django may drop a view response before (or during) send;
        # the outer HTTP lifetime is the only reliable final cleanup owner.
        try:
            await super().handle({**scope, "archivebox.own_response_stream": own}, receive, send)
        finally:
            if close is not None:
                await close()

    def create_request(self, scope, body_file):
        # ASGI already spools the complete body. Django's multipart parser
        # otherwise treats chunked uploads without Content-Length as empty.
        if not any(name == b"content-length" for name, _value in scope.get("headers", [])):
            body_file.seek(0, 2)
            length = body_file.tell()
            body_file.seek(0)
            scope = {**scope, "headers": [*scope.get("headers", []), (b"content-length", str(length).encode("ascii"))]}
        request, error = super().create_request(scope, body_file)
        if request is not None:
            bind_request_activity(request)
        return request, error


django_application = ReplayPhaseObserver(ArchiveBoxASGIHandler())


@RequestActivityObserver
async def application(scope, receive, send):
    if scope["type"] == "websocket":
        from django.urls import Resolver404, resolve
        from archivebox.plugins.discovery import get_plugin_apps
        from archivebox.plugins.host import host

        try:
            name = resolve(scope["path"]).view_name
        except Resolver404:
            name = None
        for app in get_plugin_apps().values():
            views = getattr(app, "get_websocket_views", None)
            view = views(host).get(name) if views is not None else None
            if view is not None:
                return await view(scope, receive, send)
        await send({"type": "websocket.close", "code": 1008})
        return
    return await django_application(scope, receive, send)


application = ReplayAdmission(wrap_plugin_asgi(application, settings.CONFIG.model_dump(mode="json")))
