__package__ = 'abx_plugin_ldap_auth'
__label__ = 'LDAP'
__homepage__ = 'https://github.com/django-auth-ldap/django-auth-ldap'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import LDAP_CONFIG
    
    return {
        'LDAP_CONFIG': LDAP_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import LDAP_BINARY
    
    return {
        'ldap': LDAP_BINARY,
    }


def create_superuser_from_ldap_user(sender, user=None, ldap_user=None, **kwargs):
    """
    Invoked after LDAP authenticates a user, but before they have a local User account created.
    ArchiveBox requires staff/superuser status to view the admin at all, so we must create a user
    + set staff and superuser when LDAP authenticates a new person.
    """
    from .config import LDAP_CONFIG
    
    if user is None:
        return                        # not authenticated at all
    
    if not user.id and LDAP_CONFIG.LDAP_CREATE_SUPERUSER:
        user.is_superuser = True      # authenticated via LDAP, but user is not set up in DB yet

    user.is_staff = True
    print(f'[!] WARNING: Creating new user {user} based on LDAP user {ldap_user} (is_staff={user.is_staff}, is_superuser={user.is_superuser})')


@abx.hookimpl
def ready():
    """
    Called at AppConfig.ready() time (settings + models are all loaded)
    """
    from .config import LDAP_CONFIG
    
    LDAP_CONFIG.validate()
    
    if LDAP_CONFIG.LDAP_ENABLED:
        # tell django-auth-ldap to call our function when a user is authenticated via LDAP
        import django_auth_ldap.backend
        django_auth_ldap.backend.populate_user.connect(create_superuser_from_ldap_user)
