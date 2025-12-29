"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from archivebox.config.django import setup_django

setup_django(in_memory_db=False, check_db=True)

from django.core.asgi import get_asgi_application

# Standard Django ASGI application (no websockets/channels needed)
application = get_asgi_application()

# If websocket support is needed later, install channels and use:
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.auth import AuthMiddlewareStack
# from channels.security.websocket import AllowedHostsOriginValidator
# from archivebox.core.routing import websocket_urlpatterns
#
# application = ProtocolTypeRouter({
#     "http": get_asgi_application(),
#     "websocket": AllowedHostsOriginValidator(
#         AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
#     ),
# })
