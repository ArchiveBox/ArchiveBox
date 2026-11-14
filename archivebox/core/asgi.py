"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from django.core.handlers.asgi import ASGIHandler

from archivebox.config.django import setup_django

setup_django(check_db=True)


class ArchiveBoxASGIHandler(ASGIHandler):
    def create_request(self, scope, body_file):
        # ASGI already spools the complete body. Django's multipart parser
        # otherwise treats chunked uploads without Content-Length as empty.
        if not any(name == b"content-length" for name, _value in scope.get("headers", [])):
            body_file.seek(0, 2)
            length = body_file.tell()
            body_file.seek(0)
            scope = {**scope, "headers": [*scope.get("headers", []), (b"content-length", str(length).encode("ascii"))]}
        return super().create_request(scope, body_file)


django_application = ArchiveBoxASGIHandler()


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
