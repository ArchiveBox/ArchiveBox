"""
WSGI config for archivebox project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.1/howto/deployment/wsgi/
"""

from archivebox.config.django import setup_django

setup_django(in_memory_db=False, check_db=True)


# from channels.auth import AuthMiddlewareStack
# from channels.security.websocket import AllowedHostsOriginValidator
from channels.routing import ProtocolTypeRouter  # , URLRouter
from django.core.asgi import get_asgi_application

# from core.routing import websocket_urlpatterns


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # only if we need websocket support later:
        # "websocket": AllowedHostsOriginValidator(
        #     AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        # ),
    }
)
