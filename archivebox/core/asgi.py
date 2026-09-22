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
        from archivebox.opencode.views import websocket_view

        return await websocket_view(scope, receive, send)
    return await django_application(scope, receive, send)
