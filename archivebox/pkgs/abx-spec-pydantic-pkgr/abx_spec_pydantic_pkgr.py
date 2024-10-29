__order__ = 200

import os

from typing import Dict, cast
from pathlib import Path

from pydantic_pkgr import Binary, BinProvider

import abx

from abx_spec_config import ConfigPluginSpec

###########################################################################################

class PydanticPkgrPluginSpec:

    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_LIB_DIR(self) -> Path:
        """Get the directory where shared runtime libraries/dependencies should be installed"""
        FLAT_CONFIG = pm.hook.get_FLAT_CONFIG()
        LIB_DIR = Path(FLAT_CONFIG.get('LIB_DIR', '/usr/local/share/abx'))
        return LIB_DIR
        
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_BIN_DIR(self) -> Path:
        """Get the directory where binaries should be symlinked to"""
        FLAT_CONFIG = pm.hook.get_FLAT_CONFIG()
        LIB_DIR = pm.hook.get_LIB_DIR()
        BIN_DIR = Path(FLAT_CONFIG.get('BIN_DIR') or LIB_DIR / 'bin')
        return BIN_DIR
    
    @abx.hookspec
    @abx.hookimpl
    def get_BINPROVIDERS(self) -> Dict[str, BinProvider]:
        return {
            # to be implemented by plugins, e.g.:
            # 'npm': NpmBinProvider(npm_prefix=Path('/usr/local/share/abx/npm')),
        }

    @abx.hookspec
    @abx.hookimpl
    def get_BINARIES(self) -> Dict[str, Binary]:
        return {
            # to be implemented by plugins, e.g.:
            # 'yt-dlp': Binary(name='yt-dlp', binproviders=[npm]),
        }

    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_BINPROVIDER(self, binprovider_name: str) -> BinProvider:
        """Get a specific BinProvider by name"""
        return abx.as_dict(pm.hook.get_BINPROVIDERS())[binprovider_name]

    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_BINARY(self, bin_name: str) -> Binary:
        """Get a specific Binary by name"""
        return abx.as_dict(pm.hook.get_BINARIES())[bin_name]


    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def binary_load(self, binary: Binary, **kwargs) -> Binary:
        """Load a binary from the filesystem (override to load a binary from a different source, e.g. DB, cache, etc.)"""
        loaded_binary = binary.load(**kwargs)
        pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
        return loaded_binary

    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def binary_install(self, binary: Binary, **kwargs) -> Binary:
        """Override to change how a binary is installed (e.g. by downloading from a remote source, etc.)"""
        loaded_binary = binary.install(**kwargs)
        pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
        return loaded_binary
        
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def binary_load_or_install(self, binary: Binary, **kwargs) -> Binary:
        """Override to change how a binary is loaded or installed (e.g. by downloading from a remote source, etc.)"""
        loaded_binary = binary.load_or_install(**kwargs)
        pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
        return loaded_binary

    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def binary_symlink_to_bin_dir(self, binary: Binary, bin_dir: Path | None=None):
        if not (binary.abspath and os.path.isfile(binary.abspath)):
            return
                
        BIN_DIR = pm.hook.get_BIN_DIR()
        try:
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            symlink = BIN_DIR / binary.name
            symlink.unlink(missing_ok=True)
            symlink.symlink_to(binary.abspath)
            symlink.chmod(0o777)   # make sure its executable by everyone
        except Exception:
            # print(f'[red]:warning: Failed to symlink {symlink} -> {binary.abspath}[/red] {err}')
            # not actually needed, we can just run without it
            pass


PLUGIN_SPEC = PydanticPkgrPluginSpec


class RequiredSpecsAvailable(ConfigPluginSpec, PydanticPkgrPluginSpec):
    pass

TypedPluginManager = abx.ABXPluginManager[RequiredSpecsAvailable]
pm = cast(TypedPluginManager, abx.pm)
