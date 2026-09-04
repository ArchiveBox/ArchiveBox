"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from django.core.asgi import get_asgi_application

from archivebox.config.django import setup_django

setup_django(check_db=True)

django_application = get_asgi_application()


async def application(scope, receive, send):
    if scope["type"] == "websocket":
        from archivebox.opencode.views import websocket_view

        return await websocket_view(scope, receive, send)
    return await django_application(scope, receive, send)
