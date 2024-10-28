__order__ = 100

import os
from pathlib import Path
from typing import Dict, Any, cast

from benedict import benedict


import abx

from .base_configset import BaseConfigSet, ConfigKeyStr


class ConfigPluginSpec:
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_collection_config_path(self) -> Path:
        return Path(os.getcwd()) / "ArchiveBox.conf"


    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_system_config_path(self) -> Path:
        return Path('~/.config/abx/abx.conf').expanduser()


    @abx.hookspec
    @abx.hookimpl
    def get_CONFIG(self) -> Dict[abx.PluginId, BaseConfigSet]:
        """Get the config for a single plugin -> {plugin_id: PluginConfigSet()}"""
        return {
            # override this in your plugin to return your plugin's config, e.g.
            # 'ytdlp': YtdlpConfig(...),
        }


    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_CONFIGS(self) -> Dict[abx.PluginId, BaseConfigSet]:
        """Get the config for all plugins by plugin_id -> {plugin_abc: PluginABCConfigSet(), plugin_xyz: PluginXYZConfigSet(), ...}"""
        return abx.as_dict(pm.hook.get_CONFIG())


    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_FLAT_CONFIG(self) -> Dict[ConfigKeyStr, Any]:
        """Get the flat config assembled from all plugins config -> {SOME_KEY: 'someval', 'OTHER_KEY': 'otherval', ...}"""
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in benedict(configset).items()
        })


    # TODO: add read_config_file(), write_config_file() hooks


PLUGIN_SPEC = ConfigPluginSpec


class ExpectedPluginSpec(ConfigPluginSpec):
    pass

TypedPluginManager = abx.ABXPluginManager[ExpectedPluginSpec]
pm = cast(TypedPluginManager, abx.pm)
