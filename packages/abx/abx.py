__package__ = 'abx'
__id__ = 'abx'
__label__ = 'ABX'
__author__ = 'Nick Sweeting'
__homepage__ = 'https://github.com/ArchiveBox'
__order__ = 0


import sys
import inspect
import importlib
import itertools
from pathlib import Path
from typing import Dict, Callable, List, Set, Tuple, Iterable, Any, TypedDict, Type, cast
from types import ModuleType
from typing_extensions import Annotated
from functools import cache

from benedict import benedict
from pydantic import AfterValidator

from pluggy import HookspecMarker, HookimplMarker, PluginManager, HookimplOpts

spec = hookspec = HookspecMarker("abx")
impl = hookimpl = HookimplMarker("abx")



AttrName = Annotated[str, AfterValidator(lambda x: x.isidentifier() and not x.startswith('_'))]
PluginId = Annotated[str, AfterValidator(lambda x: x.isidentifier() and not x.startswith('_') and x.islower())]

class PluginInfo(TypedDict, total=False):
    id: PluginId
    package: AttrName
    label: str
    version: str
    author: str
    homepage: str
    dependencies: List[str]
    
    source_code: str
    hooks: Dict[AttrName, Callable]
    module: ModuleType



class PatchedPluginManager(PluginManager):
    """
    Patch to fix pluggy's PluginManager to work with pydantic models.
    See: https://github.com/pytest-dev/pluggy/pull/536
    """
    def parse_hookimpl_opts(self, plugin, name: str) -> HookimplOpts | None:
        # IMPORTANT: @property methods can have side effects, and are never hookimpl
        # if attr is a property, skip it in advance
        plugin_class = plugin if inspect.isclass(plugin) else type(plugin)
        if isinstance(getattr(plugin_class, name, None), property):
            return None

        # pydantic model fields are like attrs and also can never be hookimpls
        plugin_is_pydantic_obj = hasattr(plugin, "__pydantic_core_schema__")
        if plugin_is_pydantic_obj and name in getattr(plugin, "model_fields", {}):
            # pydantic models mess with the class and attr __signature__
            # so inspect.isroutine(...) throws exceptions and cant be used
            return None
        
        try:
            return super().parse_hookimpl_opts(plugin, name)
        except AttributeError:
            return super().parse_hookimpl_opts(type(plugin), name)

pm = PatchedPluginManager("abx")



@hookspec(firstresult=True)
@hookimpl
@cache
def get_PLUGIN_ORDER(plugin: PluginId | Path | ModuleType | Type) -> Tuple[int, Path]:
    plugin_dir = None
    plugin_module = None
    
    if isinstance(plugin, str) or isinstance(plugin, Path):
        if str(plugin).endswith('.py'):
            plugin_dir = Path(plugin).parent
            plugin_id = plugin_dir.name
        elif '/' in str(plugin):
            # assume it's a path to a plugin directory
            plugin_dir = Path(plugin)
            plugin_id = plugin_dir.name
        elif str(plugin).isidentifier():
            # assume it's a plugin_id
            plugin_id = str(plugin)

    elif inspect.ismodule(plugin) or inspect.isclass(plugin):
        plugin_module = plugin
        plugin_dir = Path(str(plugin_module.__file__)).parent
        plugin_id = plugin_dir.name
    else:
        raise ValueError(f'Invalid plugin, cannot get order: {plugin}')

    if plugin_dir:
        try:
            # if .plugin_order file exists, use it to set the load priority
            order = int((plugin_dir / '.plugin_order').read_text())
            return (order, plugin_dir)
        except FileNotFoundError:
            pass
    
    if not plugin_module:
        try:
            plugin_module = importlib.import_module(plugin_id)
        except ImportError:
            raise ValueError(f'Invalid plugin, cannot get order: {plugin}')
        
    if plugin_module and not plugin_dir:
        plugin_dir = Path(str(plugin_module.__file__)).parent
    
    assert plugin_dir
    
    return (getattr(plugin_module, '__order__', 999), plugin_dir)

# @hookspec
# @hookimpl
# def get_PLUGIN() -> Dict[PluginId, PluginInfo]:
#     """Get the info for a single plugin, implemented by each plugin"""
#     return {
#         __id__: PluginInfo({
#             'id': __id__,
#             'package': str(__package__),
#             'label': __id__,
#             'version': __version__,
#             'author': __author__,
#             'homepage': __homepage__,
#             'dependencies': __dependencies__,
#         }),
#     }

@hookspec(firstresult=True)
@hookimpl
@cache
def get_PLUGIN_METADATA(plugin: PluginId | ModuleType | Type) -> PluginInfo:
    # TODO: remove get_PLUGIN hook in favor of pyproject.toml and __attr__s metdata
    # having three methods to detect plugin metadata is overkill
    
    assert plugin
    
    # import the plugin module by its name
    if isinstance(plugin, str):
        module = importlib.import_module(plugin)
        plugin_id = plugin
    elif inspect.ismodule(plugin) or inspect.isclass(plugin):
        module = plugin
        plugin_id = plugin.__package__
    else:
        raise ValueError(f'Invalid plugin, must be a module, class, or plugin ID (package name): {plugin}')
    
    assert module.__file__
    
    # load the plugin info from the plugin/__init__.py __attr__s if they exist
    plugin_module_attrs = {
        'id': getattr(module, '__id__', plugin_id),
        'name': getattr(module, '__id__', plugin_id),
        'label': getattr(module, '__label__', plugin_id),
        'version': getattr(module, '__version__', '0.0.1'),
        'author': getattr(module, '__author__', 'Unknown'),
        'homepage': getattr(module, '__homepage__', 'https://github.com/ArchiveBox'),
        'dependencies': getattr(module, '__dependencies__', []),
    }
    
    # load the plugin info from the plugin.get_PLUGIN() hook method if it has one
    plugin_info_dict = {}
    if hasattr(module, 'get_PLUGIN'):
        plugin_info_dict = {
            key.lower(): value
            for key, value in module.get_PLUGIN().items()
        }

    # load the plugin info from the plugin/pyproject.toml file if it has one
    plugin_toml_info = {}
    try:
        # try loading ./pyproject.toml first in case the plugin is a bare python file not inside a package dir
        plugin_toml_info = benedict.from_toml((Path(module.__file__).parent / 'pyproject.toml').read_text()).project
    except Exception:
        try:
            # try loading ../pyproject.toml next in case the plugin is in a packge dir
            plugin_toml_info = benedict.from_toml((Path(module.__file__).parent.parent / 'pyproject.toml').read_text()).project
        except Exception as e:
            print('WARNING: could not detect pyproject.toml for PLUGIN:', plugin_id, Path(module.__file__).parent, 'ERROR:', e)
    
    # merge the plugin info from all sources + add dyanmically calculated info
    return cast(PluginInfo, benedict(PluginInfo(**{
        'id': plugin_id,
        **plugin_module_attrs,
        **plugin_info_dict,
        **plugin_toml_info,
        'package': module.__package__,
        'module': module,
        'order': pm.hook.get_PLUGIN_ORDER(plugin=module),
        'source_code': module.__file__,
        'hooks': get_plugin_hooks(module),
    })))
    
@hookspec(firstresult=True)
@hookimpl
def get_ALL_PLUGINS() -> Dict[PluginId, PluginInfo]:
    """Get a flat dictionary of all plugins {plugin_id: {...plugin_metadata}}"""
    return as_dict(pm.hook.get_PLUGIN())

    
@hookspec(firstresult=True)
@hookimpl
def get_ALL_PLUGINS_METADATA() -> Dict[PluginId, PluginInfo]:
    """Get the metadata for all the plugins registered with Pluggy."""
    plugins = {}
    for plugin_module in pm.get_plugins():
        plugin_info = pm.hook.get_PLUGIN_METADATA(plugin=plugin_module)
        assert 'id' in plugin_info
        plugins[plugin_info['id']] = plugin_info
    return benedict(plugins)

@hookspec(firstresult=True)
@hookimpl
def get_ALL_PLUGIN_HOOK_NAMES() -> Set[str]:
    """Get a set of all hook names across all plugins"""
    return {
        hook_name
        for plugin_module in pm.get_plugins()
            for hook_name in get_plugin_hooks(plugin_module)
    }

pm.add_hookspecs(sys.modules[__name__])
pm.register(sys.modules[__name__])


###### PLUGIN DISCOVERY AND LOADING ########################################################



def register_hookspecs(plugin_ids: Iterable[PluginId]):
    """
    Register all the hookspecs from a list of module names.
    """
    for plugin_id in plugin_ids:
        hookspec_module = importlib.import_module(plugin_id)
        pm.add_hookspecs(hookspec_module)


def find_plugins_in_dir(plugins_dir: Path) -> Dict[PluginId, Path]:
    """
    Find all the plugins in a given directory. Just looks for an __init__.py file.
    """
    return {
        plugin_entrypoint.parent.name: plugin_entrypoint.parent
        for plugin_entrypoint in sorted(plugins_dir.glob("*/__init__.py"), key=pm.hook.get_PLUGIN_ORDER)   # type:ignore
        if plugin_entrypoint.parent.name != 'abx'
    }   # "plugins_pkg.pip": "/app/archivebox/plugins_pkg/pip"


def get_pip_installed_plugins(group: PluginId='abx') -> Dict[PluginId, Path]:
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



# Load all plugins from pip packages, archivebox built-ins, and user plugins
def load_plugins(plugins: Iterable[PluginId | ModuleType | Type] | Dict[PluginId, Path]):
    """
    Load all the plugins from a dictionary of module names and directory paths.
    """
    LOADED_PLUGINS = {}
    for plugin in plugins:
        plugin_info = pm.hook.get_PLUGIN_METADATA(plugin=plugin)
        assert 'id' in plugin_info and 'module' in plugin_info
        if plugin_info['module'] in pm.get_plugins():
            LOADED_PLUGINS[plugin_info['id']] = plugin_info
            continue
        try:
            pm.add_hookspecs(plugin_info['module'])
        except ValueError:
            # not all plugins register new hookspecs, some only have hookimpls
            pass
        pm.register(plugin_info['module'])
        LOADED_PLUGINS[plugin_info['id']] = plugin_info
        # print(f'    √ Loaded plugin: {plugin_id}')
    return benedict(LOADED_PLUGINS)

@cache
def get_plugin_hooks(plugin: PluginId | ModuleType | Type | None) -> Dict[AttrName, Callable]:
    """Get all the functions marked with @hookimpl on a module."""
    if not plugin:
        return {}
    
    hooks = {}
    
    if isinstance(plugin, str):
        plugin_module = importlib.import_module(plugin)
    elif inspect.ismodule(plugin) or inspect.isclass(plugin):
        plugin_module = plugin
    else:
        raise ValueError(f'Invalid plugin, cannot get hooks: {plugin}')
    
    for attr_name in dir(plugin_module):
        if attr_name.startswith('_'):
            continue
        try:
            attr = getattr(plugin_module, attr_name)
            if isinstance(attr, Callable):
                if pm.parse_hookimpl_opts(plugin_module, attr_name):
                    hooks[attr_name] = attr
        except Exception as e:
            print(f'Error getting hookimpls for {plugin}: {e}')

    return hooks


def as_list(results) -> List[Any]:
    """Flatten a list of lists returned by a pm.hook.call() into a single list"""
    return list(itertools.chain(*results))


def as_dict(results: Dict[str, Dict[PluginId, Any]] | List[Dict[PluginId, Any]]) -> Dict[PluginId, Any]:
    """Flatten a list of dicts returned by a pm.hook.call() into a single dict"""
    if isinstance(results, (dict, benedict)):
        results_list = results.values()
    else:
        results_list = results
        
    return benedict({
        result_id: result
        for plugin_results in results_list
            for result_id, result in dict(plugin_results).items()
    })


