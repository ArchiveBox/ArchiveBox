__package__ = "abx.archivebox"

import os
from typing import Dict, List, Optional
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
from archivebox.config.permissions import ARCHIVEBOX_USER

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
        
        if not (binary.abspath and os.access(binary.abspath, os.R_OK)):
            return
        
        try:
            bin_dir.mkdir(parents=True, exist_ok=True)
            symlink = bin_dir / binary.name
            symlink.unlink(missing_ok=True)
            symlink.symlink_to(binary.abspath)
            symlink.chmod(0o777)   # make sure its executable by everyone
        except Exception as err:
            # print(f'[red]:warning: Failed to symlink {symlink} -> {binary.abspath}[/red] {err}')
            # not actually needed, we can just run without it
            pass
        
    @validate_call
    def load(self, fresh=False, **kwargs) -> Self:
        if fresh:
            binary = super().load(**kwargs)
            self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
        else:
            # get cached binary from db
            try:
                from machine.models import InstalledBinary
                installed_binary = InstalledBinary.objects.get_from_db_or_cache(self)
                binary = InstalledBinary.load_from_db(installed_binary)
            except Exception:
                # maybe we are not in a DATA dir so there is no db, fallback to reading from fs
                # (e.g. when archivebox version is run outside of a DATA dir)
                binary = super().load(**kwargs)
        return binary
    
    @validate_call
    def install(self, **kwargs) -> Self:
        binary = super().install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
        return binary
    
    @validate_call
    def load_or_install(self, fresh=False, **kwargs) -> Self:
        try:
            binary = self.load(fresh=fresh)
            if binary and binary.version:
                self.symlink_to_lib(binary=binary, bin_dir=CONSTANTS.LIB_BIN_DIR)
                return binary
        except Exception:
            pass
        return self.install(**kwargs)
    
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
    
    euid: Optional[int] = ARCHIVEBOX_USER

apt = AptBinProvider()
brew = BrewBinProvider()
env = EnvBinProvider()
