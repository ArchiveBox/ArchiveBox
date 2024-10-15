__package__ = 'abx'

import importlib
from pathlib import Path
from typing import Dict, Callable, List

from . import hookspec as base_spec
from abx.hookspec import hookimpl, hookspec           # noqa
from abx.manager import pm, PluginManager             # noqa


pm.add_hookspecs(base_spec)


###### PLUGIN DISCOVERY AND LOADING ########################################################

def get_plugin_order(plugin_entrypoint: Path):
    order = 999
    try:
        # if .plugin_order file exists, use it to set the load priority
        order = int((plugin_entrypoint.parent / '.plugin_order').read_text())
    except FileNotFoundError:
        pass
    return (order, plugin_entrypoint)

def register_hookspecs(hookspecs: List[str]):
    """
    Register all the hookspecs from a list of module names.
    """
    for hookspec_import_path in hookspecs:
        hookspec_module = importlib.import_module(hookspec_import_path)
        pm.add_hookspecs(hookspec_module)


def find_plugins_in_dir(plugins_dir: Path, prefix: str) -> Dict[str, Path]:
    """
    Find all the plugins in a given directory. Just looks for an __init__.py file.
    """
    return {
        f"{prefix}.{plugin_entrypoint.parent.name}": plugin_entrypoint.parent
        for plugin_entrypoint in sorted(plugins_dir.glob("*/__init__.py"), key=get_plugin_order)
        if plugin_entrypoint.parent.name != 'abx'
    }   # "plugins_pkg.pip": "/app/archivebox/plugins_pkg/pip"


def get_pip_installed_plugins(group='abx'):
    """replaces pm.load_setuptools_entrypoints("abx"), finds plugins that registered entrypoints via pip"""
    import importlib.metadata

    DETECTED_PLUGINS = {}   # module_name: module_dir_path
    for dist in list(importlib.metadata.distributions()):
        for entrypoint in dist.entry_points:
            if entrypoint.group != group or pm.is_blocked(entrypoint.name):
                continue
            DETECTED_PLUGINS[entrypoint.name] = Path(entrypoint.load().__file__).parent
            # pm.register(plugin, name=ep.name)
            # pm._plugin_distinfo.append((plugin, DistFacade(dist)))
    return DETECTED_PLUGINS


def get_plugins_in_dirs(plugin_dirs: Dict[str, Path]):
    """
    Get the mapping of dir_name: {plugin_id: plugin_dir} for all plugins in the given directories.
    """
    DETECTED_PLUGINS = {}
    for plugin_prefix, plugin_dir in plugin_dirs.items():
        DETECTED_PLUGINS.update(find_plugins_in_dir(plugin_dir, prefix=plugin_prefix))
    return DETECTED_PLUGINS


# Load all plugins from pip packages, archivebox built-ins, and user plugins

def load_plugins(plugins_dict: Dict[str, Path]):
    """
    Load all the plugins from a dictionary of module names and directory paths.
    """
    LOADED_PLUGINS = {}
    for plugin_module, plugin_dir in plugins_dict.items():
        # print(f'Loading plugin: {plugin_module} from {plugin_dir}')
        plugin_module_loaded = importlib.import_module(plugin_module)
        pm.register(plugin_module_loaded)
        LOADED_PLUGINS[plugin_module] = plugin_module_loaded.PLUGIN
        # print(f'    √ Loaded plugin: {plugin_module}')
    return LOADED_PLUGINS

def get_registered_plugins():
    """
    Get all the plugins registered with Pluggy.
    """
    plugins = {}
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())
    for plugin in pm.get_plugins():
        plugin_info = {
            "name": plugin.__name__,
            "hooks": [h.name for h in pm.get_hookcallers(plugin) or ()],
        }
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = (
                getattr(distinfo, "name", None) or distinfo.project_name
            )
        plugins[plugin_info["name"]] = plugin_info
    return plugins




def get_plugin_hooks(plugin_pkg: str | None) -> Dict[str, Callable]:
    """
    Get all the functions marked with @hookimpl on a module.
    """
    if not plugin_pkg:
        return {}
    
    hooks = {}
    
    plugin_module = importlib.import_module(plugin_pkg)
    for attr_name in dir(plugin_module):
        if attr_name.startswith('_'):
            continue
        try:
            attr = getattr(plugin_module, attr_name)
            if isinstance(attr, Callable):
                hooks[attr_name] = None
                pm.parse_hookimpl_opts(plugin_module, attr_name)
                hooks[attr_name] = attr
        except Exception as e:
            print(f'Error getting hookimpls for {plugin_pkg}: {e}')

    return hooks
