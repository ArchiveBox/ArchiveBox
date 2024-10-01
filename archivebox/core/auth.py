__package__ = 'archivebox.core'


from archivebox.plugins_auth.ldap.apps import LDAP_CONFIG

def register_signals():

    if LDAP_CONFIG.LDAP_ENABLED:
        import django_auth_ldap.backend
        from .auth_ldap import create_user

        django_auth_ldap.backend.populate_user.connect(create_user)
