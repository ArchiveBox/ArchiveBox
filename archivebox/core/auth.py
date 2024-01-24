import os
from django.conf import settings
from ..config import (
    LDAP
)

def register_signals():

    if LDAP:
        import django_auth_ldap.backend
        from .auth_ldap import create_user

        django_auth_ldap.backend.populate_user.connect(create_user)
