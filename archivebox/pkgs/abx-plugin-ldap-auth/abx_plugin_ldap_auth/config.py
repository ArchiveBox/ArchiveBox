__package__ = 'abx_plugin_ldap_auth'

import sys

from typing import Dict, List, Optional
from pydantic import Field, computed_field

from abx_spec_config.base_configset import BaseConfigSet

LDAP_LIB = None
LDAP_SEARCH = None

def get_ldap_lib(extra_paths=()):
    global LDAP_LIB, LDAP_SEARCH
    if LDAP_LIB and LDAP_SEARCH:
        return LDAP_LIB, LDAP_SEARCH
    try:
        for path in extra_paths:
            if path not in sys.path:
                sys.path.append(path)
            
        import ldap
        from django_auth_ldap.config import LDAPSearch
        LDAP_LIB, LDAP_SEARCH = ldap, LDAPSearch
    except ImportError:
        pass
    return LDAP_LIB, LDAP_SEARCH

###################### Config ##########################


class LdapConfig(BaseConfigSet):
    """
    LDAP Config gets imported by core/settings.py very early during startup.
    It needs to be in a separate file from apps.py so that it can be imported
    during settings.py initialization before the apps are loaded.
    """

    LDAP_ENABLED: bool                  = Field(default=False, alias='LDAP')
    
    LDAP_SERVER_URI: str                = Field(default=None)
    LDAP_BIND_DN: str                   = Field(default=None)
    LDAP_BIND_PASSWORD: str             = Field(default=None)
    LDAP_USER_BASE: str                 = Field(default=None)
    LDAP_USER_FILTER: str               = Field(default=None)
    LDAP_CREATE_SUPERUSER: bool         = Field(default=False)

    LDAP_USERNAME_ATTR: str             = Field(default='username')
    LDAP_FIRSTNAME_ATTR: str            = Field(default='first_name')
    LDAP_LASTNAME_ATTR: str             = Field(default='last_name')
    LDAP_EMAIL_ATTR: str                = Field(default='email')
    
    def validate(self):
        if self.LDAP_ENABLED:
            LDAP_LIB, _LDAPSearch = get_ldap_lib()
            # Check that LDAP libraries are installed
            if LDAP_LIB is None:
                sys.stderr.write('[X] Error: LDAP Authentication is enabled but LDAP libraries are not installed. You may need to run: pip install archivebox[ldap]\n')
                # dont hard exit here. in case the user is just running "archivebox version" or "archivebox help", we still want those to work despite broken ldap
                # sys.exit(1)
                self.update_in_place(LDAP_ENABLED=False)

            # Check that all required LDAP config options are set
            if self.LDAP_CONFIG_IS_SET:
                missing_config_options = [
                    key for key, value in self.model_dump().items()
                    if value is None and key != 'LDAP_ENABLED'
                ]
                sys.stderr.write('[X] Error: LDAP_* config options must all be set if LDAP_ENABLED=True\n')
                sys.stderr.write(f'    Missing: {", ".join(missing_config_options)}\n')
                self.update_in_place(LDAP_ENABLED=False)
        return self
    
    @computed_field
    @property
    def LDAP_CONFIG_IS_SET(self) -> bool:
        """Check that all required LDAP config options are set"""
        if self.LDAP_ENABLED:
            LDAP_LIB, _LDAPSearch = get_ldap_lib()
            return bool(LDAP_LIB) and self.LDAP_ENABLED and bool(
                self.LDAP_SERVER_URI
                and self.LDAP_BIND_DN
                and self.LDAP_BIND_PASSWORD
                and self.LDAP_USER_BASE
                and self.LDAP_USER_FILTER
            )
        return False

    @computed_field
    @property
    def LDAP_USER_ATTR_MAP(self) -> Dict[str, str]:
        return {
            'username': self.LDAP_USERNAME_ATTR,
            'first_name': self.LDAP_FIRSTNAME_ATTR,
            'last_name': self.LDAP_LASTNAME_ATTR,
            'email': self.LDAP_EMAIL_ATTR,
        }

    @computed_field
    @property
    def AUTHENTICATION_BACKENDS(self) -> List[str]:
        if self.LDAP_ENABLED:
            return [
                'django.contrib.auth.backends.ModelBackend',
                'django_auth_ldap.backend.LDAPBackend',
            ]
        return []

    @computed_field
    @property
    def AUTH_LDAP_USER_SEARCH(self) -> Optional[object]:
        if self.LDAP_ENABLED:
            LDAP_LIB, LDAPSearch = get_ldap_lib()
            return self.LDAP_USER_FILTER and LDAPSearch(
                self.LDAP_USER_BASE,
                LDAP_LIB.SCOPE_SUBTREE,                                                                         # type: ignore
                '(&(' + self.LDAP_USERNAME_ATTR + '=%(user)s)' + self.LDAP_USER_FILTER + ')',
            )
        return None


LDAP_CONFIG = LdapConfig()
