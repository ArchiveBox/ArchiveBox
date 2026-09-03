"""
ASGI config for archivebox project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

from django.core.asgi import get_asgi_application

from archivebox.config.django import setup_django

setup_django(check_db=True)

# Standard Django ASGI application (no websockets/channels needed)
application = get_asgi_application()
