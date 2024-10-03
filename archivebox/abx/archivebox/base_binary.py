__package__ = "abx.archivebox"

from typing import Dict, List
from typing_extensions import Self

from pydantic import Field, InstanceOf, validate_call
from pydantic_pkgr import (
    Binary,
    BinProvider,
    BinProviderName,
    ProviderLookupDict,
    AptProvider,
    BrewProvider,
    EnvProvider,
)

from archivebox.config import CONSTANTS

import abx
from .base_hook import BaseHook, HookType


class BaseBinProvider(BaseHook, BinProvider):
    hook_type: HookType = "BINPROVIDER"

    # def on_get_abspath(self, bin_name: BinName, **context) -> Optional[HostBinPath]:
    #     Class = super()
    #     get_abspath_func = lambda: Class.on_get_abspath(bin_name, **context)
    #     # return cache.get_or_set(f'bin:abspath:{bin_name}', get_abspath_func)
    #     return get_abspath_func()

    # def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
    #     Class = super()
    #     get_version_func = lambda: Class.on_get_version(bin_name, abspath, **context)
    #     # return cache.get_or_set(f'bin:version:{bin_name}:{abspath}', get_version_func)
    #     return get_version_func()

    
    # TODO: add install/load/load_or_install methods as abx.hookimpl methods
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/binproviders/NpmBinProvider/   TODO
        return "/admin/environment/binaries/"

    @abx.hookimpl
    def get_BINPROVIDERS(self):
        return [self]

class BaseBinary(BaseHook, Binary):
    hook_type: HookType = "BINARY"

    binproviders_supported: List[InstanceOf[BinProvider]] = Field(default_factory=list, alias="binproviders")
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default_factory=dict, alias="overrides")

    @staticmethod
    def symlink_to_lib(binary, bin_dir=None) -> None:
        bin_dir = bin_dir or CONSTANTS.LIB_BIN_DIR
        
        if not (binary.abspath and binary.abspath.exists()):
            return
        
        bin_dir.mkdir(parents=True, exist_ok=True)
        symlink = bin_dir / binary.name
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(binary.abspath)
        symlink.chmod(0o777)   # make sure its executable by everyone
        
    @validate_call
    def load(self, **kwargs) -> Self:
        binary = super().load(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
        return binary
    
    @validate_call
    def install(self, **kwargs) -> Self:
        binary = super().install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
        return binary
    
    @validate_call
    def load_or_install(self, **kwargs) -> Self:
        binary = super().load_or_install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
        return binary
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/config/LdapConfig/
        return f"/admin/environment/binaries/{self.name}/"

    @abx.hookimpl
    def get_BINARIES(self):
        return [self]


class AptBinProvider(AptProvider, BaseBinProvider):
    name: BinProviderName = "apt"
    
class BrewBinProvider(BrewProvider, BaseBinProvider):
    name: BinProviderName = "brew"
    
class EnvBinProvider(EnvProvider, BaseBinProvider):
    name: BinProviderName = "env"

apt = AptBinProvider()
brew = BrewBinProvider()
env = EnvBinProvider()
