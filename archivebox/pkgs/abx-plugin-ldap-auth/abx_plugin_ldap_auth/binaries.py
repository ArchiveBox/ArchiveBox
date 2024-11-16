__package__ = 'abx_plugin_ldap_auth'

import inspect

from typing import List
from pathlib import Path
from pydantic import InstanceOf

from abx_pkg import BinaryOverrides, SemVer, Binary, BinProvider

from abx_plugin_default_binproviders import apt
from abx_plugin_pip.binproviders import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER, VENV_SITE_PACKAGES, LIB_SITE_PACKAGES, USER_SITE_PACKAGES, SYS_SITE_PACKAGES

from .config import get_ldap_lib



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


class LdapBinary(Binary):
    name: str = 'ldap'
    description: str = 'LDAP Authentication'
    binproviders_supported: List[InstanceOf[BinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER, apt]

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
