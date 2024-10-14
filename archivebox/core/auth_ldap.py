from archivebox.plugins_auth.ldap.apps import LDAP_CONFIG

def create_user(sender, user=None, ldap_user=None, **kwargs):
    if not user.id and LDAP_CONFIG.LDAP_CREATE_SUPERUSER:
        user.is_superuser = True

    user.is_staff = True
    print(f'[!] WARNING: Creating new user {user} based on LDAP user {ldap_user} (is_staff={user.is_staff}, is_superuser={user.is_superuser})')
