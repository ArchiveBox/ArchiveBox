"""Django app configuration for LDAP authentication."""

__package__ = "archivebox.ldap"

from django.apps import AppConfig


class LDAPConfig(AppConfig):
    """Django app config for LDAP authentication."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'archivebox.ldap'
    verbose_name = 'LDAP Authentication'
