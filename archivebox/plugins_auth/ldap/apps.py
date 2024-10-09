__package__ = 'archivebox.plugins_auth.ldap'


import inspect

from typing import List, Dict
from pathlib import Path
from pydantic import InstanceOf

from pydantic_pkgr import BinProviderName, ProviderLookupDict, SemVer

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, apt

from plugins_pkg.pip.apps import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER, VENV_SITE_PACKAGES, LIB_SITE_PACKAGES, USER_SITE_PACKAGES, SYS_SITE_PACKAGES
from .settings import LDAP_CONFIG, get_ldap_lib


###################### Config ##########################

def get_LDAP_LIB_path(paths):
    LDAP_LIB = get_ldap_lib()[0]
    if not LDAP_LIB:
        return None
    
    # check that LDAP_LIB path is in one of the specified site packages dirs
    lib_path = Path(inspect.getfile(LDAP_LIB))
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

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        LIB_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path(LIB_SITE_PACKAGES),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": lambda: ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path(VENV_SITE_PACKAGES),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": lambda: ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: get_LDAP_LIB_path((*USER_SITE_PACKAGES, *SYS_SITE_PACKAGES)),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": lambda: ['python-ldap>=3.4.3', 'django-auth-ldap>=4.1.0'],
        },
        apt.name: {
            "abspath": lambda: get_LDAP_LIB_path(SYS_SITE_PACKAGES),
            "version": lambda: get_LDAP_LIB_version(),
            "packages": lambda: ['libssl-dev', 'libldap2-dev', 'libsasl2-dev', 'python3-ldap', 'python3-msgpack', 'python3-mutagen'],
        },
    }

LDAP_BINARY = LdapBinary()


class LdapAuthPlugin(BasePlugin):
    app_label: str = 'ldap'
    verbose_name: str = 'LDAP Authentication'

    hooks: List[InstanceOf[BaseHook]] = [
        LDAP_CONFIG,
        LDAP_BINARY,
    ]


PLUGIN = LdapAuthPlugin()
DJANGO_APP = PLUGIN.AppConfig
