"""
LDAP Django Settings Integration Hook

This hook configures Django's LDAP authentication backend when LDAP is enabled.
"""

__package__ = 'archivebox.plugins.ldap'

from typing import Dict, Any


def on_Django__10_ldap_settings(django_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Configure Django LDAP authentication settings.

    This hook runs during Django setup to configure the django-auth-ldap backend
    when LDAP_ENABLED=True.
    """
    from archivebox.config.configset import get_config

    config = get_config()
    ldap_enabled = config.get('LDAP_ENABLED', False)

    # Convert string to bool if needed
    if isinstance(ldap_enabled, str):
        ldap_enabled = ldap_enabled.lower() in ('true', 'yes', '1')

    if not ldap_enabled:
        # LDAP not enabled, nothing to configure
        return django_settings

    try:
        from django_auth_ldap.config import LDAPSearch
        import ldap
    except ImportError:
        from rich.console import Console
        console = Console(stderr=True)
        console.print('[red][X] Error:[/red] LDAP is enabled but required packages are not installed')
        console.print('[yellow]Hint:[/yellow] Install LDAP dependencies:')
        console.print('  pip install archivebox[ldap]')
        console.print('  # or')
        console.print('  apt install python3-ldap && pip install django-auth-ldap')
        import sys
        sys.exit(1)

    # Configure LDAP authentication
    django_settings['AUTH_LDAP_SERVER_URI'] = config.get('LDAP_SERVER_URI')
    django_settings['AUTH_LDAP_BIND_DN'] = config.get('LDAP_BIND_DN')
    django_settings['AUTH_LDAP_BIND_PASSWORD'] = config.get('LDAP_BIND_PASSWORD')

    # Configure user search
    user_base = config.get('LDAP_USER_BASE')
    user_filter = config.get('LDAP_USER_FILTER', '(uid=%(user)s)')
    django_settings['AUTH_LDAP_USER_SEARCH'] = LDAPSearch(
        user_base,
        ldap.SCOPE_SUBTREE,
        user_filter
    )

    # Map LDAP attributes to Django user model fields
    django_settings['AUTH_LDAP_USER_ATTR_MAP'] = {
        'username': config.get('LDAP_USERNAME_ATTR', 'uid'),
        'first_name': config.get('LDAP_FIRSTNAME_ATTR', 'givenName'),
        'last_name': config.get('LDAP_LASTNAME_ATTR', 'sn'),
        'email': config.get('LDAP_EMAIL_ATTR', 'mail'),
    }

    # Configure user flags
    create_superuser = config.get('LDAP_CREATE_SUPERUSER', False)
    if isinstance(create_superuser, str):
        create_superuser = create_superuser.lower() in ('true', 'yes', '1')

    if create_superuser:
        django_settings['AUTH_LDAP_USER_FLAGS_BY_GROUP'] = {}
        # All LDAP users get superuser status
        django_settings['AUTH_LDAP_ALWAYS_UPDATE_USER'] = True

    # Configure authentication backend to always create users
    django_settings['AUTH_LDAP_ALWAYS_UPDATE_USER'] = True

    # Add LDAP authentication backend to AUTHENTICATION_BACKENDS
    if 'AUTHENTICATION_BACKENDS' not in django_settings:
        django_settings['AUTHENTICATION_BACKENDS'] = []

    # Insert LDAP backend before ModelBackend but after RemoteUserBackend
    ldap_backend = 'django_auth_ldap.backend.LDAPBackend'

    # Remove it if it already exists to avoid duplicates
    backends = [b for b in django_settings['AUTHENTICATION_BACKENDS'] if b != ldap_backend]

    # Insert LDAP backend in the right position
    if 'django.contrib.auth.backends.RemoteUserBackend' in backends:
        idx = backends.index('django.contrib.auth.backends.RemoteUserBackend') + 1
        backends.insert(idx, ldap_backend)
    else:
        # Insert at the beginning
        backends.insert(0, ldap_backend)

    django_settings['AUTHENTICATION_BACKENDS'] = backends

    return django_settings
