"""
WSGI config for archivebox project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.1/howto/deployment/wsgi/
"""

from archivebox.config.legacy import setup_django

setup_django(in_memory_db=False, check_db=True)


from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Just HTTP for now. (We can add other protocols later.)
    }
)
