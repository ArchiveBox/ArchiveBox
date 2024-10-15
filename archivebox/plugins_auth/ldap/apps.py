__package__ = 'archivebox.plugins_auth.ldap'


import inspect

from typing import List
from pathlib import Path
from pydantic import InstanceOf

from pydantic_pkgr import BinaryOverrides, SemVer

import abx

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, apt

from plugins_pkg.pip.apps import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER, VENV_SITE_PACKAGES, LIB_SITE_PACKAGES, USER_SITE_PACKAGES, SYS_SITE_PACKAGES
from .settings import LDAP_CONFIG, get_ldap_lib


###################### Config ##########################

def get_LDAP_LIB_path(paths=()):
    LDAP_LIB = get_ldap_lib()[0]
    if not LDAP_LIB:
        return None
    
    # check that LDAP_LIB path is in one of the specified site packages dirs
    lib_path = Path(inspect.getfile(LDAP_LIB))
    if not paths:
        return lib_path
    
    for site_packges_dir in paths:
        if str(lib_path.parent.parent.resolve()) == str(Path(site_packges_dir).resolve()):
            return lib_path
    return None

def get_LDAP_LIB_version():
    LDAP_LIB = get_ldap_lib()[0]
    return LDAP_LIB and SemVer(LDAP_LIB.__version__)

class LdapBinary(BaseBinary):
    name: str = 'ldap'
    description: str = 'LDAP Authentication'
    binproviders_supported: List[InstanceOf[BaseBinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER, apt]

    overrides: BinaryOverrides = {
        LIB_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path(LIB_SITE_PACKAGES),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path(VENV_SITE_PACKAGES),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path((*USER_SITE_PACKAGES, *SYS_SITE_PACKAGES)),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        apt.name: {
            "abspath": lambda: get_LDAP_LIB_path(),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": ['libssl-dev', 'libldap2-dev', 'libsasl2-dev', 'python3-ldap', 'python3-msgpack', 'python3-mutagen'],
        },
    }

LDAP_BINARY = LdapBinary()


def create_superuser_from_ldap_user(sender, user=None, ldap_user=None, **kwargs):
    if user is None:
        # not authenticated at all
        return
    
    if not user.id and LDAP_CONFIG.LDAP_CREATE_SUPERUSER:
        # authenticated via LDAP, but user is not set up in DB yet
        user.is_superuser = True

    user.is_staff = True
    print(f'[!] WARNING: Creating new user {user} based on LDAP user {ldap_user} (is_staff={user.is_staff}, is_superuser={user.is_superuser})')


class LdapAuthPlugin(BasePlugin):
    app_label: str = 'ldap'
    verbose_name: str = 'LDAP Authentication'

    hooks: List[InstanceOf[BaseHook]] = [
        LDAP_CONFIG,
        *([LDAP_BINARY] if LDAP_CONFIG.LDAP_ENABLED else []),
    ]
    
    @abx.hookimpl
    def ready(self):
        super().ready()
        
        if LDAP_CONFIG.LDAP_ENABLED:
            import django_auth_ldap.backend
            django_auth_ldap.backend.populate_user.connect(create_superuser_from_ldap_user)
        

PLUGIN = LdapAuthPlugin()
DJANGO_APP = PLUGIN.AppConfig
