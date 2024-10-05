__package__ = 'archivebox.plugins_auth.ldap'

import inspect

from typing import List, Dict
from pathlib import Path
from pydantic import InstanceOf

from pydantic_pkgr import BinProviderName, ProviderLookupDict, SemVer

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider

from plugins_pkg.pip.apps import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER
from .settings import LDAP_CONFIG, get_ldap_lib


###################### Config ##########################

LDAP_LIB = lambda: get_ldap_lib()[0]   # lazy load to avoid slow ldap lib import on startup


class LdapBinary(BaseBinary):
    name: str = 'ldap'
    description: str = 'LDAP Authentication'
    binproviders_supported: List[InstanceOf[BaseBinProvider]] = [VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        VENV_PIP_BINPROVIDER.name: {
            "abspath": lambda: LDAP_LIB() and Path(inspect.getfile(LDAP_LIB())),         # type: ignore
            "version": lambda: LDAP_LIB() and SemVer(LDAP_LIB().__version__),            # type: ignore
            "packages": lambda: ['archivebox[ldap]'],
        },
        SYS_PIP_BINPROVIDER.name: {
            "abspath": lambda: LDAP_LIB() and Path(inspect.getfile(LDAP_LIB())),         # type: ignore
            "version": lambda: LDAP_LIB() and SemVer(LDAP_LIB().__version__),            # type: ignore
            "packages": lambda: ['archivebox[ldap]'],
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
