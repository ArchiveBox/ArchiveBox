from django.conf import settings
from ..config import (
    LDAP_CREATE_SUPERUSER
)

def create_user(sender, user=None, ldap_user=None, **kwargs):

    if not user.id and LDAP_CREATE_SUPERUSER:
        user.is_superuser = True

    user.is_staff = True
