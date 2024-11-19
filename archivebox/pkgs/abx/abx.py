__package__ = 'abx'
__id__ = 'abx'
__label__ = 'ABX'
__author__ = 'Nick Sweeting'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox'
__order__ = 0

import sys
import inspect
import importlib
import itertools
from pathlib import Path
from typing import Dict, Callable, List, Set, Tuple, Iterable, Any, TypeVar, TypedDict, Type, cast, Generic, Mapping, overload, Final, ParamSpec, Literal, Protocol
from types import ModuleType
from typing_extensions import Annotated
from functools import cache

from benedict import benedict
from pydantic import AfterValidator

from pluggy import HookimplMarker, PluginManager, HookimplOpts, HookspecOpts, HookCaller



ParamsT = ParamSpec("ParamsT")
ReturnT = TypeVar('ReturnT')

class HookSpecDecoratorThatReturnsFirstResult(Protocol):    
    """Type of a plugin method decorated with @hookspec(firstresult=True), which returns a single result (from the first plugin that implements the hook)"""
    def __call__(self, func: Callable[ParamsT, ReturnT]) -> Callable[ParamsT, ReturnT]: ...

class HookSpecDecoratorThatReturnsListResults(Protocol):
    """Type of a plugin method decorated with @hookspec(firstresult=False), which returns a list of results (one for each plugin that implements the hook)"""
    def __call__(self, func: Callable[ParamsT, ReturnT]) -> Callable[ParamsT, List[ReturnT]]: ...


class TypedHookspecMarker:
    """
    Improved version of pluggy.HookspecMarker that supports type inference of hookspecs with firstresult=True|False correctly
    https://github.com/pytest-dev/pluggy/issues/191
    """

    __slots__ = ('project_name',)
    
    def __init__(self, project_name: str) -> None:
        self.project_name: Final[str] = project_name

    # handle @hookspec(firstresult=False) -> List[ReturnT] (test_firstresult_False_hookspec)
    @overload
    def __call__(
        self,
        function: None = ...,
        firstresult: Literal[False] = ...,
        historic: bool = ...,
        warn_on_impl: Warning | None = ...,
        warn_on_impl_args: Mapping[str, Warning] | None = ...,
    ) -> HookSpecDecoratorThatReturnsListResults: ...

    # handle @hookspec(firstresult=True) -> ReturnT (test_firstresult_True_hookspec)
    @overload
    def __call__(
        self,
        function: None = ...,
        firstresult: Literal[True] = ...,
        historic: bool = ...,
        warn_on_impl: Warning | None = ...,
        warn_on_impl_args: Mapping[str, Warning] | None = ...,
    ) -> HookSpecDecoratorThatReturnsFirstResult: ...
    
    # handle @hookspec -> List[ReturnT] (test_normal_hookspec)
    # order matters!!! this one has to come last
    @overload
    def __call__(
        self,
        function: Callable[ParamsT, ReturnT] = ...,
        firstresult: Literal[False] = ...,
        historic: bool = ...,
        warn_on_impl: None = ...,
        warn_on_impl_args: None = ...,
    ) -> Callable[ParamsT, List[ReturnT]]: ...

    def __call__(
        self,
        function: Callable[ParamsT, ReturnT] | None = None,
        firstresult: bool = False,
        historic: bool = False,
        warn_on_impl: Warning | None = None,
        warn_on_impl_args: Mapping[str, Warning] | None = None,
    ) -> Callable[ParamsT, List[ReturnT]] | HookSpecDecoratorThatReturnsListResults | HookSpecDecoratorThatReturnsFirstResult:
        
        def setattr_hookspec_opts(func) -> Callable:
            if historic and firstresult:
                raise ValueError("cannot have a historic firstresult hook")
            opts: HookspecOpts = {
                "firstresult": firstresult,
                "historic": historic,
                "warn_on_impl": warn_on_impl,
                "warn_on_impl_args": warn_on_impl_args,
            }
            setattr(func, self.project_name + "_spec", opts)
            return func

        if function is not None:
            return setattr_hookspec_opts(function)
        else:
            return setattr_hookspec_opts




spec = hookspec = TypedHookspecMarker("abx")
impl = hookimpl = HookimplMarker("abx")


def is_valid_attr_name(x: str) -> str:
    """Check if a string is a valid attribute name (used to validate hook method names on a plugin)"""
    assert x.isidentifier() and not x.startswith('_')
    return x

def is_valid_module_name(x: str) -> str:
    """Check if a string e.g. "some_pkg.some_plugin_name" is a valid module name (used to validate plugin IDs)"""
    assert x.isidentifier() and not x.startswith('_') and x.islower()
    return x

AttrName = Annotated[str, AfterValidator(is_valid_attr_name)]
PluginId = Annotated[str, AfterValidator(is_valid_module_name)]


class PluginInfo(TypedDict, total=True):
    """Full Metadata Dictionary containing all info about a plugin, returned by abx.get_plugin()"""
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
    


PluginSpec = TypeVar("PluginSpec")

class ABXPluginManager(PluginManager, Generic[PluginSpec]):
    """
    Patch to fix pluggy's PluginManager to work with pydantic models.
    See: https://github.com/pytest-dev/pluggy/pull/536
    """
    
    # enable static type checking of pm.hook.call() calls
    # https://stackoverflow.com/a/62871889/2156113
    # https://github.com/pytest-dev/pluggy/issues/191
    hook: PluginSpec
    
    def create_typed_hookcaller(self, name: str, module_or_class: Type[PluginSpec], spec_opts: HookspecOpts) -> HookCaller:
        """
        create a new HookCaller subclass with a modified __signature__
        so that the return type is correct and args are converted to kwargs
        """
        TypedHookCaller = type('TypedHookCaller', (HookCaller,), {})
        
        hookspec_signature = inspect.signature(getattr(module_or_class, name))
        hookspec_return_type = hookspec_signature.return_annotation
        
        # replace return type with list if firstresult=False
        hookcall_return_type = hookspec_return_type if spec_opts['firstresult'] else List[hookspec_return_type]
        
        # replace each arg with kwarg equivalent (pm.hook.call() only accepts kwargs)
        args_as_kwargs = [
            param.replace(kind=inspect.Parameter.KEYWORD_ONLY) if param.name != 'self' else param
            for param in hookspec_signature.parameters.values()
        ]
        TypedHookCaller.__signature__ = hookspec_signature.replace(parameters=args_as_kwargs, return_annotation=hookcall_return_type)
        TypedHookCaller.__name__ = f'{name}_HookCaller'
        
        return TypedHookCaller(name, self._hookexec, module_or_class, spec_opts)
    
    def add_hookspecs(self, module_or_class: Type[PluginSpec]) -> None:
        """Add HookSpecs from the given class, (generic type allows us to enforce types of pm.hook.call() statically)"""
        names = []
        for name in dir(module_or_class):
            spec_opts = self.parse_hookspec_opts(module_or_class, name)
            if spec_opts is not None:
                hc: HookCaller | None = getattr(self.hook, name, None)
                if hc is None:
                    hc = self.create_typed_hookcaller(name, module_or_class, spec_opts)
                    setattr(self.hook, name, hc)
                else:
                    # Plugins registered this hook without knowing the spec.
                    hc.set_specification(module_or_class, spec_opts)
                    for hookfunction in hc.get_hookimpls():
                        self._verify_hook(hc, hookfunction)
                names.append(name)
                
        if not names:
            raise ValueError(
                f"did not find any {self.project_name!r} hooks in {module_or_class!r}"
            )

    def parse_hookimpl_opts(self, plugin, name: str) -> HookimplOpts | None:
        # IMPORTANT: @property methods can have side effects, and are never hookimpl
        # if attr is a property, skip it in advance
        # plugin_class = plugin if inspect.isclass(plugin) else type(plugin)
        if isinstance(getattr(plugin, name, None), property):
            return None
        
        try:
            return super().parse_hookimpl_opts(plugin, name)
        except AttributeError:
            return None


pm = ABXPluginManager("abx")



def get_plugin_order(plugin: PluginId | Path | ModuleType | Type) -> Tuple[int, Path]:
    """Get the order a plugin should be loaded in by reading its ./.plugin_order file or .__order__ attr"""
    assert plugin
    plugin_module = None
    plugin_dir = None
    
    if isinstance(plugin, str) or isinstance(plugin, Path):
        if str(plugin).endswith('.py'):
            plugin_dir = Path(plugin).parent
        elif '/' in str(plugin):
            # assume it's a path to a plugin directory
            plugin_dir = Path(plugin)
        elif str(plugin).isidentifier():
            pass

    elif inspect.ismodule(plugin):
        plugin_module = plugin
        plugin_dir = Path(str(plugin_module.__file__)).parent
    elif inspect.isclass(plugin):
        plugin_module = plugin
        plugin_dir = Path(inspect.getfile(plugin)).parent
    else:
        raise ValueError(f'Invalid plugin, cannot get order: {plugin}')

    if plugin_dir:
        try:
            # if .plugin_order file exists, use it to set the load priority
            order = int((plugin_dir / '.plugin_order').read_text())
            assert -1000000 < order < 100000000
            return (order, plugin_dir)
        except FileNotFoundError:
            pass
    
    default_order = 10 if '_spec_' in str(plugin_dir).lower() else 999
    
    if plugin_module:
        order = getattr(plugin_module, '__order__', default_order)
    else:
        order = default_order
    
    assert order is not None
    assert plugin_dir
    
    return (order, plugin_dir)


# @cache
def get_plugin(plugin: PluginId | ModuleType | Type) -> PluginInfo:
    """Get the full PluginInfo metadata for a plugin, given its plugin ID, module, or class"""
    assert plugin
    
    # import the plugin module by its name
    if isinstance(plugin, str):
        module = importlib.import_module(plugin)
        # print('IMPORTED PLUGIN:', plugin)
        plugin = getattr(module, 'PLUGIN_SPEC', getattr(module, 'PLUGIN', module))
    elif inspect.ismodule(plugin):
        module = plugin
        plugin = getattr(module, 'PLUGIN_SPEC', getattr(module, 'PLUGIN', module))
    elif inspect.isclass(plugin):
        module = inspect.getmodule(plugin)
    else:
        plugin = type(plugin)
        module = inspect.getmodule(plugin)
        
        # raise ValueError(f'Invalid plugin, must be a module, class, or plugin ID (package name): {plugin}')
    
    assert module and hasattr(module, '__package__')
    
    plugin_file = Path(inspect.getfile(module))
    plugin_package = module.__package__ or module.__name__
    plugin_id = plugin_package.replace('.', '_')
    
    # load the plugin info from the plugin/__init__.py __attr__s if they exist
    plugin_module_attrs = {
        'label': getattr(module, '__label__', plugin_id),
        'version': getattr(module, '__version__', '0.0.1'),
        'author': getattr(module, '__author__', 'ArchiveBox'),
        'homepage': getattr(module, '__homepage__', 'https://github.com/ArchiveBox'),
        'dependencies': getattr(module, '__dependencies__', []),
    }

    # load the plugin info from the plugin/pyproject.toml file if it has one
    plugin_toml_info = {}
    try:
        # try loading ./pyproject.toml first in case the plugin is a bare python file not inside a package dir
        plugin_toml_info = benedict.from_toml((plugin_file.parent / 'pyproject.toml').read_text()).project
    except Exception:
        try:
            # try loading ../pyproject.toml next in case the plugin is in a packge dir
            plugin_toml_info = benedict.from_toml((plugin_file.parent.parent / 'pyproject.toml').read_text()).project
        except Exception:
            # print('WARNING: could not detect pyproject.toml for PLUGIN:', plugin_id, plugin_file.parent, 'ERROR:', e)
            pass
    
    
    assert plugin_id
    assert plugin_package
    assert module.__file__
    
    # merge the plugin info from all sources + add dyanmically calculated info
    return cast(PluginInfo, benedict(PluginInfo(**{
        'id': plugin_id,
        **plugin_module_attrs,
        **plugin_toml_info,
        'package': plugin_package,
        'source_code': module.__file__,
        'order': get_plugin_order(plugin),
        'hooks': get_plugin_hooks(plugin),
        'module': module,
        'plugin': plugin,
    })))


def get_all_plugins() -> Dict[PluginId, PluginInfo]:
    """Get the PluginInfo metadata for all the loaded plugins"""
    plugins = {}
    for plugin_module in pm.get_plugins():
        plugin_info = get_plugin(plugin=plugin_module)
        assert 'id' in plugin_info
        plugins[plugin_info['id']] = plugin_info
    return benedict(plugins)


def get_all_hook_names() -> Set[str]:
    """Get the names of all hookspec/hookimpl methods available across all loaded plugins"""
    return {
        hook_name
        for plugin_module in pm.get_plugins()
            for hook_name in get_plugin_hooks(plugin_module)
    }
    

def get_all_hook_specs() -> Dict[str, Dict[str, Any]]:
    """Get a set of all hookspec methods defined in all plugins (useful for type checking if a pm.hook.call() is valid)"""
    hook_specs = {}
    
    for hook_name in get_all_hook_names():
        for plugin_module in pm.get_plugins():
            if inspect.ismodule(plugin_module):
                plugin = plugin_module
                plugin_module = plugin_module
            elif inspect.isclass(plugin_module):
                plugin = plugin_module
                plugin_module = inspect.getmodule(plugin)
            else:
                plugin = type(plugin_module)
                plugin_module = inspect.getmodule(plugin)

            assert plugin and plugin_module and hasattr(plugin_module, '__package__')
                
            if hasattr(plugin, hook_name):
                hookspecopts = pm.parse_hookspec_opts(plugin, hook_name)
                if hookspecopts:
                    method = getattr(plugin, hook_name)
                    signature = inspect.signature(method)
                    return_type = signature.return_annotation if signature.return_annotation != inspect._empty else None
                    
                    if hookspecopts.get('firstresult'):
                        return_type = return_type
                    else:
                        # if not firstresult, return_type is a sequence
                        return_type = List[return_type]
                        
                    call_signature = signature.replace(return_annotation=return_type)
                    method = lambda *args, **kwargs: getattr(pm.hook, hook_name)(*args, **kwargs)
                    method.__signature__ = call_signature
                    method.__name__ = hook_name
                    method.__package__ = plugin_module.__package__
                    
                    hook_specs[hook_name] = {
                        'name': hook_name,
                        'method': method,
                        'signature': call_signature,
                        'hookspec_opts': hookspecopts,
                        'hookspec_signature': signature,
                        'hookspec_plugin': method.__package__,
                    }
                
    return benedict(hook_specs)
    


###### PLUGIN DISCOVERY AND LOADING ########################################################


def find_plugins_in_dir(plugins_dir: Path) -> Dict[PluginId, Path]:
    """
    Find all the plugins in a given directory. Just looks for an __init__.py file.
    """
    python_dirs = plugins_dir.glob("*/__init__.py")
    sorted_python_dirs = sorted(python_dirs, key=lambda p: get_plugin_order(plugin=p) or 500)
    
    return {
        plugin_entrypoint.parent.name: plugin_entrypoint.parent
        for plugin_entrypoint in sorted_python_dirs
        if plugin_entrypoint.parent.name not in ('abx', 'core')
    }


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
    PLUGINS_TO_LOAD = []
    LOADED_PLUGINS = {}
    
    plugin_infos = sorted([
        get_plugin(plugin)
        for plugin in plugins
    ], key=lambda plugin: plugin.get('order', 999))
    
    
    for plugin_info in plugin_infos:
        assert plugin_info, 'No plugin metadata found for plugin'
        assert 'id' in plugin_info and 'module' in plugin_info
        if plugin_info['module'] in pm.get_plugins():
            LOADED_PLUGINS[plugin_info['id']] = plugin_info
            continue
        else:
            PLUGINS_TO_LOAD.append(plugin_info)

    PLUGINS_TO_LOAD = sorted(PLUGINS_TO_LOAD, key=lambda x: x['order'])
        
    for plugin_info in PLUGINS_TO_LOAD:
        # if '--version' not in sys.argv and '--help' not in sys.argv:
        #     print(f'🧩 Loading plugin: {plugin_info["id"]}...', end='\r', flush=True, file=sys.stderr)
        pm.register(plugin_info['module'])
        LOADED_PLUGINS[plugin_info['id']] = plugin_info
    # print('\x1b[2K', end='\r', flush=True, file=sys.stderr)
    return benedict(LOADED_PLUGINS)

@cache
def get_plugin_hooks(plugin: PluginId | ModuleType | Type | None) -> Dict[AttrName, Callable]:
    """Get all the functions marked with @hookimpl on a plugin module or class."""
    if not plugin:
        return {}
    
    hooks = {}
    
    if isinstance(plugin, str):
        plugin_module = importlib.import_module(plugin)
    elif inspect.ismodule(plugin) or inspect.isclass(plugin):
        plugin_module = plugin
    else:
        plugin_module = type(plugin)
        # raise ValueError(f'Invalid plugin, cannot get hooks: {plugin}')
    
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

ReturnT = TypeVar('ReturnT')

def as_list(results: List[List[ReturnT]]) -> List[ReturnT]:
    """Flatten a list of lists returned by a pm.hook.call() into a single list of [result1, result2, ...]"""
    return list(itertools.chain(*results))


def as_dict(results: List[Dict[PluginId, ReturnT]]) -> Dict[PluginId, ReturnT]:
    """Flatten a list of dicts returned by a pm.hook.call() into a single dict of {plugin_id1: result1, plugin_id2: result2, ...}"""
    
    if isinstance(results, (dict, benedict)):
        results_list = results.values()
    else:
        results_list = results
        
    return benedict({
        result_id: result
        for plugin_results in results_list
            for result_id, result in plugin_results.items()
    })
