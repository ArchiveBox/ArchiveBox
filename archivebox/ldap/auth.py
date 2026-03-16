"""
LDAP authentication backend for ArchiveBox.

This module extends django-auth-ldap to support the LDAP_CREATE_SUPERUSER flag.
"""

__package__ = "archivebox.ldap"

import importlib

try:
    BaseLDAPBackend = importlib.import_module("django_auth_ldap.backend").LDAPBackend
except ImportError:
    class BaseLDAPBackend:
        """Dummy LDAP backend when django-auth-ldap is not installed."""

        pass


class ArchiveBoxLDAPBackend(BaseLDAPBackend):
    """
    Custom LDAP authentication backend for ArchiveBox.

    Extends django-auth-ldap's LDAPBackend to support:
    - LDAP_CREATE_SUPERUSER: Automatically grant superuser privileges to LDAP users
    """

    def authenticate_ldap_user(self, ldap_user, password):
        """
        Authenticate using LDAP and optionally grant superuser privileges.

        This method is called by django-auth-ldap after successful LDAP authentication.
        """
        from archivebox.config.ldap import LDAP_CONFIG

        base_authenticate = getattr(super(), "authenticate_ldap_user", None)
        if base_authenticate is None:
            return None

        user = base_authenticate(ldap_user, password)

        if user and LDAP_CONFIG.LDAP_CREATE_SUPERUSER:
            # Grant superuser privileges to all LDAP-authenticated users
            if not user.is_superuser:
                user.is_superuser = True
                user.is_staff = True
                user.save()

        return user
