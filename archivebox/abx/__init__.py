import itertools
import importlib
from pathlib import Path
from typing import Dict
from benedict import benedict

import pluggy
import archivebox

from . import hookspec as base_spec
from .hookspec import hookimpl, hookspec           # noqa


pm = pluggy.PluginManager("abx")
pm.add_hookspecs(base_spec)

def register_hookspecs(hookspecs):
    for hookspec_import_path in hookspecs:
        hookspec_module = importlib.import_module(hookspec_import_path)
        pm.add_hookspecs(hookspec_module)


def find_plugins_in_dir(plugins_dir: Path, prefix: str) -> Dict[str, Path]:
    return {
        f"{prefix}.{plugin_entrypoint.parent.name}": plugin_entrypoint.parent
        for plugin_entrypoint in sorted(plugins_dir.glob("*/apps.py"))  # key=get_plugin_order  # Someday enforcing plugin import order may be required, but right now it's not needed
    }   # "plugins_pkg.pip": "/app/archivebox/plugins_pkg/pip"


def get_pip_installed_plugins(group='abx'):
    """replaces pm.load_setuptools_entrypoints("abx")"""
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
    DETECTED_PLUGINS = {}
    for plugin_prefix, plugin_dir in plugin_dirs.items():
        DETECTED_PLUGINS.update(find_plugins_in_dir(plugin_dir, prefix=plugin_prefix))
    return DETECTED_PLUGINS

def get_builtin_plugins():
    PLUGIN_DIRS = {
        'plugins_sys':             archivebox.PACKAGE_DIR / 'plugins_sys',
        'plugins_pkg':             archivebox.PACKAGE_DIR / 'plugins_pkg',
        'plugins_auth':            archivebox.PACKAGE_DIR / 'plugins_auth',
        'plugins_search':          archivebox.PACKAGE_DIR / 'plugins_search',
        'plugins_extractor':       archivebox.PACKAGE_DIR / 'plugins_extractor',
    }
    DETECTED_PLUGINS = {}
    for plugin_prefix, plugin_dir in PLUGIN_DIRS.items():
        DETECTED_PLUGINS.update(find_plugins_in_dir(plugin_dir, prefix=plugin_prefix))
    return DETECTED_PLUGINS

def get_user_plugins():
    return find_plugins_in_dir(archivebox.DATA_DIR / 'user_plugins', prefix='user_plugins')


# BUILTIN_PLUGINS = get_builtin_plugins()
# PIP_PLUGINS = get_pip_installed_plugins()
# USER_PLUGINS = get_user_plugins()
# ALL_PLUGINS = {**BUILTIN_PLUGINS, **PIP_PLUGINS, **USER_PLUGINS}

# Load all plugins from pip packages, archivebox built-ins, and user plugins

def load_plugins(plugins_dict: Dict[str, Path]):
    LOADED_PLUGINS = {}
    for plugin_module, plugin_dir in plugins_dict.items():
        # print(f'Loading plugin: {plugin_module} from {plugin_dir}')
        plugin_module_loaded = importlib.import_module(plugin_module + '.apps')
        pm.register(plugin_module_loaded)
        LOADED_PLUGINS[plugin_module] = plugin_module_loaded.PLUGIN
        # print(f'    √ Loaded plugin: {plugin_module}')
    return LOADED_PLUGINS

def get_registered_plugins():
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


def get_plugins_INSTALLLED_APPS():
    return itertools.chain(*pm.hook.get_INSTALLED_APPS())

def register_plugins_INSTALLLED_APPS(INSTALLED_APPS):
    pm.hook.register_INSTALLED_APPS(INSTALLED_APPS=INSTALLED_APPS)


def get_plugins_MIDDLEWARE():
    return itertools.chain(*pm.hook.get_MIDDLEWARE())

def register_plugins_MIDDLEWARE(MIDDLEWARE):
    pm.hook.register_MIDDLEWARE(MIDDLEWARE=MIDDLEWARE)


def get_plugins_AUTHENTICATION_BACKENDS():
    return itertools.chain(*pm.hook.get_AUTHENTICATION_BACKENDS())

def register_plugins_AUTHENTICATION_BACKENDS(AUTHENTICATION_BACKENDS):
    pm.hook.register_AUTHENTICATION_BACKENDS(AUTHENTICATION_BACKENDS=AUTHENTICATION_BACKENDS)


def get_plugins_STATICFILES_DIRS():
    return itertools.chain(*pm.hook.get_STATICFILES_DIRS())

def register_plugins_STATICFILES_DIRS(STATICFILES_DIRS):
    pm.hook.register_STATICFILES_DIRS(STATICFILES_DIRS=STATICFILES_DIRS)


def get_plugins_TEMPLATE_DIRS():
    return itertools.chain(*pm.hook.get_TEMPLATE_DIRS())

def register_plugins_TEMPLATE_DIRS(TEMPLATE_DIRS):
    pm.hook.register_TEMPLATE_DIRS(TEMPLATE_DIRS=TEMPLATE_DIRS)

def get_plugins_DJANGO_HUEY_QUEUES():
    HUEY_QUEUES = {}
    for plugin_result in pm.hook.get_DJANGO_HUEY_QUEUES():
        HUEY_QUEUES.update(plugin_result)
    return HUEY_QUEUES

def register_plugins_DJANGO_HUEY(DJANGO_HUEY):
    pm.hook.register_DJANGO_HUEY(DJANGO_HUEY=DJANGO_HUEY)

def get_plugins_ADMIN_DATA_VIEWS_URLS():
    return itertools.chain(*pm.hook.get_ADMIN_DATA_VIEWS_URLS())

def register_plugins_ADMIN_DATA_VIEWS(ADMIN_DATA_VIEWS):
    pm.hook.register_ADMIN_DATA_VIEWS(ADMIN_DATA_VIEWS=ADMIN_DATA_VIEWS)


def register_plugins_settings(settings):
    # convert settings dict to an benedict so we can set values using settings.attr = xyz notation
    settings_as_obj = benedict(settings, keypath_separator=None)
    
    # set default values for settings that are used by plugins
    settings_as_obj.INSTALLED_APPS = settings_as_obj.get('INSTALLED_APPS', [])
    settings_as_obj.MIDDLEWARE = settings_as_obj.get('MIDDLEWARE', [])
    settings_as_obj.AUTHENTICATION_BACKENDS = settings_as_obj.get('AUTHENTICATION_BACKENDS', [])
    settings_as_obj.STATICFILES_DIRS = settings_as_obj.get('STATICFILES_DIRS', [])
    settings_as_obj.TEMPLATE_DIRS = settings_as_obj.get('TEMPLATE_DIRS', [])
    settings_as_obj.DJANGO_HUEY = settings_as_obj.get('DJANGO_HUEY', {'queues': {}})
    settings_as_obj.ADMIN_DATA_VIEWS = settings_as_obj.get('ADMIN_DATA_VIEWS', {'URLS': []})
    
    # call all the hook functions to mutate the settings values in-place
    register_plugins_INSTALLLED_APPS(settings_as_obj.INSTALLED_APPS)
    register_plugins_MIDDLEWARE(settings_as_obj.MIDDLEWARE)
    register_plugins_AUTHENTICATION_BACKENDS(settings_as_obj.AUTHENTICATION_BACKENDS)
    register_plugins_STATICFILES_DIRS(settings_as_obj.STATICFILES_DIRS)
    register_plugins_TEMPLATE_DIRS(settings_as_obj.TEMPLATE_DIRS)
    register_plugins_DJANGO_HUEY(settings_as_obj.DJANGO_HUEY)
    register_plugins_ADMIN_DATA_VIEWS(settings_as_obj.ADMIN_DATA_VIEWS)
    
    # calls Plugin.settings(settings) on each registered plugin
    pm.hook.register_settings(settings=settings_as_obj)
    
    # then finally update the settings globals() object will all the new settings
    settings.update(settings_as_obj)


def get_plugins_urlpatterns():
    return list(itertools.chain(*pm.hook.urlpatterns()))

def register_plugins_urlpatterns(urlpatterns):
    pm.hook.register_urlpatterns(urlpatterns=urlpatterns)


# PLUGANTIC HOOKS

def get_plugins_PLUGINS():
    return benedict({
        plugin.PLUGIN.id: plugin.PLUGIN
        for plugin in pm.get_plugins()
    })

def get_plugins_HOOKS(PLUGINS):
    return benedict({
        hook.id: hook
        for plugin in PLUGINS.values()
            for hook in plugin.hooks
    })

def get_plugins_CONFIGS():
    return benedict({
        config.id: config
        for plugin_configs in pm.hook.get_CONFIGS()
            for config in plugin_configs
    })
    
def get_plugins_FLAT_CONFIG(CONFIGS):
    FLAT_CONFIG = {}
    for config in CONFIGS.values():
        FLAT_CONFIG.update(config.model_dump())
    return benedict(FLAT_CONFIG)

def get_plugins_BINPROVIDERS():
    return benedict({
        binprovider.id: binprovider
        for plugin_binproviders in pm.hook.get_BINPROVIDERS()
            for binprovider in plugin_binproviders
    })

def get_plugins_BINARIES():
    return benedict({
        binary.id: binary
        for plugin_binaries in pm.hook.get_BINARIES()
            for binary in plugin_binaries
    })

def get_plugins_EXTRACTORS():
    return benedict({
        extractor.id: extractor
        for plugin_extractors in pm.hook.get_EXTRACTORS()
            for extractor in plugin_extractors
    })

def get_plugins_REPLAYERS():
    return benedict({
        replayer.id: replayer
        for plugin_replayers in pm.hook.get_REPLAYERS()
            for replayer in plugin_replayers
    })

def get_plugins_CHECKS():
    return benedict({
        check.id: check
        for plugin_checks in pm.hook.get_CHECKS()
            for check in plugin_checks
    })

def get_plugins_ADMINDATAVIEWS():
    return benedict({
        admin_dataview.id: admin_dataview
        for plugin_admin_dataviews in pm.hook.get_ADMINDATAVIEWS()
            for admin_dataview in plugin_admin_dataviews
    })

def get_plugins_QUEUES():
    return benedict({
        queue.id: queue
        for plugin_queues in pm.hook.get_QUEUES()
            for queue in plugin_queues
    })

def get_plugins_SEARCHBACKENDS():
    return benedict({
        searchbackend.id: searchbackend
        for plugin_searchbackends in pm.hook.get_SEARCHBACKENDS()
            for searchbackend in plugin_searchbackends
    })
