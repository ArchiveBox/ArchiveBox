__order__ = 100

import os
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING

from benedict import benedict

if TYPE_CHECKING:
    from archivebox.config.constants import ConstantsDict

import abx

from .base_configset import BaseConfigSet, ConfigKeyStr


class ConfigPluginSpec:
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_collection_config_path() -> Path:
        return Path(os.getcwd()) / "ArchiveBox.conf"


    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_system_config_path() -> Path:
        return Path('~/.config/abx/abx.conf').expanduser()


    @staticmethod
    @abx.hookspec
    @abx.hookimpl
    def get_CONFIG() -> dict[abx.PluginId, 'BaseConfigSet | ConstantsDict']:
        from archivebox import CONSTANTS
        """Get the config for a single plugin -> {plugin_id: PluginConfigSet()}"""
        return {
            'CONSTANTS': CONSTANTS,
        }


    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_CONFIGS() -> dict[abx.PluginId, 'BaseConfigSet | ConstantsDict']:
        """Get the config for all plugins by plugin_id -> {plugin_abc: PluginABCConfigSet(), plugin_xyz: PluginXYZConfigSet(), ...}"""
        return abx.as_dict(pm.hook.get_CONFIG())


    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_FLAT_CONFIG() -> dict[ConfigKeyStr, Any]:
        """Get the flat config assembled from all plugins config -> {SOME_KEY: 'someval', 'OTHER_KEY': 'otherval', ...}"""
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in benedict(configset).items()
        })
        
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_SCOPE_CONFIG(extra=None, archiveresult=None, snapshot=None, crawl=None, user=None, request=None, collection=..., environment=..., machine=..., default=...) -> dict[ConfigKeyStr, Any]:
        """Get the config as it applies to you right now, based on the current context"""
        return benedict({
            **pm.hook.get_default_config(default=default),                       # schema defaults defined in source code
            **pm.hook.get_machine_config(machine=machine),                       # machine defaults set on the Machine model
            **pm.hook.get_environment_config(environment=environment),           # env config set for just this run on this machine
            **pm.hook.get_collection_config(collection=collection),              # collection defaults set in ArchiveBox.conf
            **pm.hook.get_user_config(user=user),                                # user config set on User model
            **pm.hook.get_request_config(request=request),                       # extra config derived from the current request
            **pm.hook.get_crawl_config(crawl=crawl),                             # extra config set on the Crawl model
            **pm.hook.get_snapshot_config(snapshot=snapshot),                    # extra config set on the Snapshot model
            **pm.hook.get_archiveresult_config(archiveresult=archiveresult),     # extra config set on the ArchiveResult model
            **(extra or {}),                                                     # extra config passed in by the caller
        })
        
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_request_config(request=None) -> dict:
        if not request:
            return {}
        return request.session.get('config', None) or {}
        
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_archiveresult_config(archiveresult=None) -> dict[ConfigKeyStr, Any]:
        if not archiveresult:
            return {}
        return getattr(archiveresult, 'config', None) or {}
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_snapshot_config(snapshot) -> dict[ConfigKeyStr, Any]:
        return getattr(snapshot, 'config', None) or {}
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_crawl_config(crawl=None) -> dict[ConfigKeyStr, Any]:
        if not crawl:
            return {}
        return getattr(crawl, 'config', None) or {}
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_user_config(user=None) -> dict[ConfigKeyStr, Any]:
        return getattr(user, 'config', None) or {}
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_collection_config(collection=...) -> dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the collection config from the active data/ArchiveBox.conf file
        # {} = empty dict, override to ignore the collection config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in (configset.from_collection().items() if isinstance(configset, BaseConfigSet) else {})
        }) if collection == ... else collection
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_environment_config(environment=...) -> dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the environment config from the active environment variables
        # {} = empty dict, override to ignore the environment config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in (configset.from_environment().items() if isinstance(configset, BaseConfigSet) else ())
        }) if environment == ... else environment
    
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_machine_config(machine=...) -> dict:
        # ... = ellipsis, means automatically get the machine config from the currently executing machine
        # {} = empty dict, override to ignore the machine config
        # if machine == ...:
        #     machine = Machine.objects.get_current()
        return getattr(machine, 'config', None) or {}
        
    @staticmethod
    @abx.hookspec(firstresult=True)
    @abx.hookimpl
    def get_default_config(default=...) -> dict[ConfigKeyStr, Any]:
        # ... = ellipsis, means automatically get the machine config from the currently executing machine
        # {} = empty dict, override to ignore the machine config
        return benedict({
            key: value
            for configset in pm.hook.get_CONFIGS().values()
                for key, value in (configset.from_defaults().items() if isinstance(configset, BaseConfigSet) else configset.items())
        }) if default == ... else default


    # TODO: add read_config_file(), write_config_file() hooks


PLUGIN_SPEC = ConfigPluginSpec


class ExpectedPluginSpec(ConfigPluginSpec):
    pass

TypedPluginManager = abx.ABXPluginManager[ExpectedPluginSpec]
pm = cast(TypedPluginManager, abx.pm)
