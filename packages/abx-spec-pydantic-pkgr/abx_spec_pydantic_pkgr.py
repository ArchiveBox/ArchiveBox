import os

from typing import Dict
from pathlib import Path

import abx

from pydantic_pkgr import Binary, BinProvider

###########################################################################################

@abx.hookspec
@abx.hookimpl()
def get_BINPROVIDERS() -> Dict[str, BinProvider]:
    return {}

@abx.hookspec
@abx.hookimpl()
def get_BINARIES() -> Dict[str, Binary]:
    return {}

@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_BINPROVIDER(binprovider_name: str) -> BinProvider:
    return abx.as_dict(abx.pm.hook.get_BINPROVIDERS())[binprovider_name]

@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_BINARY(bin_name: str) -> BinProvider:
    return abx.as_dict(abx.pm.hook.get_BINARYS())[bin_name]


@abx.hookspec(firstresult=True)
@abx.hookimpl
def binary_load(binary: Binary, **kwargs) -> Binary:
    loaded_binary = binary.load(**kwargs)
    abx.pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
    return loaded_binary

@abx.hookspec(firstresult=True)
@abx.hookimpl
def binary_install(binary: Binary, **kwargs) -> Binary:
    loaded_binary = binary.install(**kwargs)
    abx.pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
    return loaded_binary
    
@abx.hookspec(firstresult=True)
@abx.hookimpl
def binary_load_or_install(binary: Binary, **kwargs) -> Binary:
    loaded_binary = binary.load_or_install(**kwargs)
    abx.pm.hook.binary_symlink_to_bin_dir(binary=loaded_binary)
    return loaded_binary

@abx.hookspec(firstresult=True)
@abx.hookimpl
def binary_symlink_to_bin_dir(binary: Binary, bin_dir: Path | None=None):
    LIB_DIR = Path(abx.pm.hook.get_CONFIG().get('LIB_DIR', '/usr/local/share/abx'))
    BIN_DIR = bin_dir or Path(abx.pm.hook.get_CONFIG().get('BIN_DIR', LIB_DIR / 'bin'))
            
    if not (binary.abspath and os.path.isfile(binary.abspath)):
        return
            
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
