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
        
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_SCOPE_CONFIG(self, extra=None, archiveresult=None, snapshot=None, crawl=None, user=None, collection=..., environment=..., machine=..., default=...) -> Dict[ConfigKeyStr, Any]:
        """Get the config as it applies to you right now, based on the current context"""
        return benedict({
            **pm.hook.get_default_config(default=default),
            # **pm.hook.get_machine_config(machine),
            **pm.hook.get_environment_config(environment=environment),
            **pm.hook.get_collection_config(collection=collection),
            **pm.hook.get_user_config(user=user),
            **pm.hook.get_crawl_config(crawl=crawl),
            **pm.hook.get_snapshot_config(snapshot=snapshot),
            **pm.hook.get_archiveresult_config(archiveresult=archiveresult),
            # **pm.hook.get_request_config(request=request),
            **(extra or {}),
        })
        
    # @abx.hookspec(firstresult=True)
    # @abx.hookimpl
    # def get_request_config(self, request) -> dict:
    #     session = getattr(request, 'session', None)
    #     return getattr(session, 'config', None) or {}
        
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_archiveresult_config(self, archiveresult) -> Dict[ConfigKeyStr, Any]:
        return getattr(archiveresult, 'config', None) or {}
    
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_snapshot_config(self, snapshot) -> Dict[ConfigKeyStr, Any]:
        return getattr(snapshot, 'config', None) or {}
    
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_crawl_config(self, crawl) -> Dict[ConfigKeyStr, Any]:
        return getattr(crawl, 'config', None) or {}
    
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_user_config(self, user=None) -> Dict[ConfigKeyStr, Any]:
        return getattr(user, 'config', None) or {}
    
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_collection_config(self, collection=...) -> Dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the collection config from the active data/ArchiveBox.conf file
        # {} = empty dict, override to ignore the collection config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in configset.from_collection().items()
        }) if collection == ... else collection
    
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_environment_config(self, environment=...) -> Dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the environment config from the active environment variables
        # {} = empty dict, override to ignore the environment config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in configset.from_environment().items()
        }) if environment == ... else environment
    
    # @abx.hookspec(firstresult=True)
    # @abx.hookimpl
    # def get_machine_config(self, machine=...) -> dict:
    #     # ... = ellipsis, means automatically get the machine config from the currently executing machine
    #     # {} = empty dict, override to ignore the machine config
    #     if machine == ...:
    #         machine = Machine.objects.get_current()
    #     return getattr(machine, 'config', None) or {}
        
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_default_config(self, default=...) -> Dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the machine config from the currently executing machine
        # {} = empty dict, override to ignore the machine config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in configset.from_defaults().items()
        }) if default == ... else default


    # TODO: add read_config_file(), write_config_file() hooks


PLUGIN_SPEC = ConfigPluginSpec


class ExpectedPluginSpec(ConfigPluginSpec):
    pass

TypedPluginManager = abx.ABXPluginManager[ExpectedPluginSpec]
pm = cast(TypedPluginManager, abx.pm)
