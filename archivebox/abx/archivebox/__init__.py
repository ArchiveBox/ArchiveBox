__package__ = 'abx.archivebox'

import os
import importlib

from typing import Dict
from pathlib import Path


def load_archivebox_plugins(pm, plugins_dict: Dict[str, Path]):
    """Load archivebox plugins, very similar to abx.load_plugins but it looks for a pydantic PLUGIN model + hooks in apps.py"""
    LOADED_PLUGINS = {}
    for plugin_module, plugin_dir in plugins_dict.items():
        # print(f'Loading plugin: {plugin_module} from {plugin_dir}')
        
        archivebox_plugins_found = []
        
        # 1. register the plugin module directly in case it contains any look hookimpls (e.g. in __init__.py)
        plugin_module_loaded = importlib.import_module(plugin_module)
        pm.register(plugin_module_loaded)
        if hasattr(plugin_module_loaded, 'PLUGIN'):
            archivebox_plugins_found.append(plugin_module_loaded.PLUGIN)
        
        # 2. then try to import plugin_module.apps as well
        if os.access(plugin_dir / 'apps.py', os.R_OK):
            plugin_apps = importlib.import_module(plugin_module + '.apps')
            pm.register(plugin_apps)                                           # register the whole .apps  in case it contains loose hookimpls (not in a class)
            if hasattr(plugin_apps, 'PLUGIN'):
                archivebox_plugins_found.append(plugin_apps.PLUGIN)
        
        # 3. then try to look for plugin_module.PLUGIN and register it + all its hooks
        for ab_plugin in archivebox_plugins_found:
            pm.register(ab_plugin)
            for hook in ab_plugin.hooks:
                hook.__signature__ = hook.__class__.__signature__              # fix to make pydantic model usable as Pluggy plugin
                pm.register(hook)
            LOADED_PLUGINS[plugin_module] = ab_plugin
            
        # print(f'    √ Loaded plugin: {LOADED_PLUGINS}')
    return LOADED_PLUGINS
