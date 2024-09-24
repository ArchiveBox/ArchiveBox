__package__ = "archivebox.plugantic"

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

from django.conf import settings

from .base_hook import BaseHook, HookType
from ..config_stubs import AttrDict


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

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        settings.BINPROVIDERS = getattr(settings, "BINPROVIDERS", None) or AttrDict({})
        settings.BINPROVIDERS[self.id] = self

        super().register(settings, parent_plugin=parent_plugin)
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/binproviders/NpmBinProvider/   TODO
        return "/admin/environment/binaries/"


class BaseBinary(BaseHook, Binary):
    hook_type: HookType = "BINARY"

    binproviders_supported: List[InstanceOf[BinProvider]] = Field(default_factory=list, alias="binproviders")
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default_factory=dict, alias="overrides")

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        settings.BINARIES = getattr(settings, "BINARIES", None) or AttrDict({})
        settings.BINARIES[self.id] = self

        super().register(settings, parent_plugin=parent_plugin)

    @staticmethod
    def symlink_to_lib(binary, bin_dir=settings.CONFIG.BIN_DIR) -> None:
        if not (binary.abspath and binary.abspath.exists()):
            return
        
        bin_dir.mkdir(parents=True, exist_ok=True)
        
        symlink = bin_dir / binary.name
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(binary.abspath)

    @validate_call
    def load(self, **kwargs) -> Self:
        binary = super().load(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=settings.CONFIG.BIN_DIR)
        return binary
    
    @validate_call
    def install(self, **kwargs) -> Self:
        binary = super().install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=settings.CONFIG.BIN_DIR)
        return binary
    
    @validate_call
    def load_or_install(self, **kwargs) -> Self:
        binary = super().load_or_install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=settings.CONFIG.BIN_DIR)
        return binary
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/config/LdapConfig/
        return f"/admin/environment/binaries/{self.name}/"

apt = AptProvider()
brew = BrewProvider()
env = EnvProvider()
