import os
from pathlib import Path
from typing import Dict, Any

from benedict import benedict


import abx

from .base_configset import BaseConfigSet, ConfigKeyStr


@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_collection_config_path() -> Path:
    return Path(os.getcwd()) / "ArchiveBox.conf"


@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_system_config_path() -> Path:
    return Path('~/.config/abx/abx.conf').expanduser()


@abx.hookspec
@abx.hookimpl
def get_CONFIG() -> Dict[abx.PluginId, BaseConfigSet]:
    """Get the config for a single plugin -> {plugin_id: PluginConfigSet()}"""
    return {}


@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_CONFIGS() -> Dict[abx.PluginId, BaseConfigSet]:
    """Get the config for all plugins by plugin_id -> {plugin_abc: PluginABCConfigSet(), plugin_xyz: PluginXYZConfigSet(), ...}"""
    return abx.as_dict(abx.pm.hook.get_CONFIG())


@abx.hookspec(firstresult=True)
@abx.hookimpl
def get_FLAT_CONFIG() -> Dict[ConfigKeyStr, Any]:
    """Get the flat config assembled from all plugins config -> {SOME_KEY: 'someval', 'OTHER_KEY': 'otherval', ...}"""
    return benedict({
        key: value
        for configset in get_CONFIGS().values()
            for key, value in benedict(configset).items()
    })


# TODO: add read_config_file(), write_config_file() hooks
