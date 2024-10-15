__package__ = 'abx.archivebox'

import os
import importlib

from typing import Dict
from pathlib import Path


def load_archivebox_plugins(pm, plugins_dict: Dict[str, Path]):
    """Load archivebox plugins, very similar to abx.load_plugins but it looks for a pydantic PLUGIN model + hooks in apps.py"""
    LOADED_PLUGINS = {}
    for plugin_module, plugin_dir in reversed(plugins_dict.items()):
        # print(f'Loading plugin: {plugin_module} from {plugin_dir}')
        
        # 1. register the plugin module directly in case it contains any look hookimpls (e.g. in __init__.py)
        try:
            plugin_module_loaded = importlib.import_module(plugin_module)
            pm.register(plugin_module_loaded)
        except Exception as e:
            print(f'Error registering plugin: {plugin_module} - {e}')
            
        
        # 2. then try to import plugin_module.apps as well
        if os.access(plugin_dir / 'apps.py', os.R_OK):
            plugin_apps = importlib.import_module(plugin_module + '.apps')
            pm.register(plugin_apps)                                           # register the whole .apps  in case it contains loose hookimpls (not in a class)
            
        # print(f'    √ Loaded plugin: {plugin_module} {len(archivebox_plugins_found) * "🧩"}')
    return LOADED_PLUGINS
