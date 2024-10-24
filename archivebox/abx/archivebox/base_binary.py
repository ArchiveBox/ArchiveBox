__package__ = "abx.archivebox"

import os
from typing import Optional, cast
from typing_extensions import Self

from pydantic import validate_call
from pydantic_pkgr import (
    Binary,
    BinProvider,
    BinProviderName,
    AptProvider,
    BrewProvider,
    EnvProvider,
)

from archivebox.config.permissions import ARCHIVEBOX_USER

import abx


class BaseBinProvider(BinProvider):
    
    # TODO: add install/load/load_or_install methods as abx.hookimpl methods
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/binproviders/NpmBinProvider/   TODO
        return "/admin/environment/binaries/"

    @abx.hookimpl
    def get_BINPROVIDERS(self):
        return [self]

class BaseBinary(Binary):
    # TODO: formalize state diagram, final states, transitions, side effects, etc.

    @staticmethod
    def symlink_to_lib(binary, bin_dir=None) -> None:
        from archivebox.config.common import STORAGE_CONFIG
        bin_dir = bin_dir or STORAGE_CONFIG.LIB_DIR / 'bin'
        
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
        from archivebox.config.common import STORAGE_CONFIG
        if fresh:
            binary = super().load(**kwargs)
            self.symlink_to_lib(binary=binary, bin_dir=STORAGE_CONFIG.LIB_DIR / 'bin')
        else:
            # get cached binary from db
            try:
                from machine.models import InstalledBinary
                installed_binary = InstalledBinary.objects.get_from_db_or_cache(self)    # type: ignore
                binary = InstalledBinary.load_from_db(installed_binary)
            except Exception:
                # maybe we are not in a DATA dir so there is no db, fallback to reading from fs
                # (e.g. when archivebox version is run outside of a DATA dir)
                binary = super().load(**kwargs)
        return cast(Self, binary)
    
    @validate_call
    def install(self, **kwargs) -> Self:
        from archivebox.config.common import STORAGE_CONFIG
        binary = super().install(**kwargs)
        self.symlink_to_lib(binary=binary, bin_dir=STORAGE_CONFIG.LIB_DIR / 'bin')
        return binary
    
    @validate_call
    def load_or_install(self, fresh=False, **kwargs) -> Self:
        from archivebox.config.common import STORAGE_CONFIG
        try:
            binary = self.load(fresh=fresh)
            if binary and binary.version:
                self.symlink_to_lib(binary=binary, bin_dir=STORAGE_CONFIG.LIB_DIR / 'bin')
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
