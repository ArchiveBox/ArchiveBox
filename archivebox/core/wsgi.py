"""
WSGI config for archivebox project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.1/howto/deployment/wsgi/
"""

import archivebox                                       # noqa
from archivebox.config.django import setup_django

setup_django(in_memory_db=False, check_db=True)

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
