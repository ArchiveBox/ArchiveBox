__package__ = 'archivebox.plugantic'

import inspect
from huey.api import TaskWrapper

from pathlib import Path
from typing import Tuple, Literal, ClassVar, get_args
from pydantic import BaseModel, ConfigDict


HookType = Literal['CONFIG', 'BINPROVIDER', 'BINARY', 'EXTRACTOR', 'REPLAYER', 'CHECK', 'ADMINDATAVIEW', 'QUEUE', 'SEARCHBACKEND']
hook_type_names: Tuple[HookType] = get_args(HookType)

class BaseHook(BaseModel):
    """
    A Plugin consists of a list of Hooks, applied to django.conf.settings when AppConfig.read() -> Plugin.register() is called.
    Plugin.register() then calls each Hook.register() on the provided settings.
    each Hook.regsiter() function (ideally pure) takes a django.conf.settings as input and returns a new one back.
    or 
    it modifies django.conf.settings in-place to add changes corresponding to its HookType.
    e.g. for a HookType.CONFIG, the Hook.register() function places the hook in settings.CONFIG (and settings.HOOKS)
    An example of an impure Hook would be a CHECK that modifies settings but also calls django.core.checks.register(check).
    In practice any object that subclasses BaseHook and provides a .register() function can behave as a Hook.

    setup_django() -> imports all settings.INSTALLED_APPS...
        # django imports AppConfig, models, migrations, admins, etc. for all installed apps
        # django then calls AppConfig.ready() on each installed app...

        plugins_pkg.npm.NpmPlugin().AppConfig.ready()                    # called by django
            plugins_pkg.npm.NpmPlugin().register(settings) ->
                plugins_pkg.npm.NpmConfigSet().register(settings)
                    plugantic.base_configset.BaseConfigSet().register(settings)
                        plugantic.base_hook.BaseHook().register(settings, parent_plugin=plugins_pkg.npm.NpmPlugin())

                ...
        ...

    Both core ArchiveBox code and plugin code depend on python >= 3.10 and django >= 5.0 w/ sqlite and a filesystem.
    Core ArchiveBox code can depend only on python and the pip libraries it ships with, and can never depend on plugin code / node / other binaries.
    Plugin code can depend on archivebox core, other django apps, other pip libraries, and other plugins.
    Plugins can provide BinProviders + Binaries which can depend on arbitrary other binaries / package managers like curl / wget / yt-dlp / etc.

    The execution interface between plugins is simply calling builtinplugins.npm.... functions directly, django handles
    importing all plugin code. There is no need to manually register methods/classes, only register to call
    impure setup functions or provide runtime state.
    settings.CONFIGS / settings.BINPROVIDERS / settings.BINARIES /... etc. are reserved for dynamic runtime state only.
    This state is exposed to the broader system in a flat namespace, e.g. CONFIG.IS_DOCKER=True, or BINARIES = [
        ..., Binary('node', abspath='/usr/local/bin/node', version='22.2.0'), ...
    ]

    """
    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        from_attributes=True,
        populate_by_name=True,
        validate_defaults=True,
        validate_assignment=False,
        revalidate_instances="subclass-instances",
        ignored_types=(TaskWrapper, ),
    )
    
    hook_type: ClassVar[HookType]     # e.g. = 'CONFIG'
    
    # verbose_name: str = Field()
    
    _is_registered: bool = False
    _is_ready: bool = False


    @property
    def id(self) -> str:
        return self.__class__.__name__

    @property
    def hook_module(self) -> str:
        """e.g. plugins_extractor.singlefile.apps.SinglefileConfigSet"""
        return f'{self.__module__}.{self.__class__.__name__}'

    @property
    def hook_file(self) -> Path:
        """e.g. plugins_extractor.singlefile.apps.SinglefileConfigSet"""
        return Path(inspect.getfile(self.__class__))

    @property
    def plugin_module(self) -> str:
        """e.g. plugins_extractor.singlefile"""
        return f"{self.__module__}.{self.__class__.__name__}".split("archivebox.", 1)[-1].rsplit(".apps.", 1)[0]

    @property
    def plugin_dir(self) -> Path:
        return Path(inspect.getfile(self.__class__)).parent.resolve()
    
    @property
    def admin_url(self) -> str:
        # e.g. /admin/environment/config/LdapConfig/
        return f"/admin/environment/{self.hook_type.lower()}/{self.id}/"


    def register(self, settings, parent_plugin=None):
        """Load a record of an installed hook into global Django settings.HOOKS at runtime."""
        self._plugin = parent_plugin         # for debugging only, never rely on this!

        # assert json.dumps(self.model_json_schema(), indent=4), f"Hook {self.hook_module} has invalid JSON schema."

        print('  -', self.hook_module, '.register()')

        # record installed hook in settings.HOOKS
        settings.HOOKS[self.id] = self

        if settings.HOOKS[self.id]._is_registered:
            raise Exception(f"Tried to run {self.hook_module}.register() but its already been called!")

        settings.HOOKS[self.id]._is_registered = True

        # print("REGISTERED HOOK:", self.hook_module)

    def ready(self, settings):
        """Runs any runtime code needed when AppConfig.ready() is called (after all models are imported)."""

        print('  -', self.hook_module, '.ready()')

        assert self.id in settings.HOOKS, f"Tried to ready hook {self.hook_module} but it is not registered in settings.HOOKS."

        if settings.HOOKS[self.id]._is_ready:
            raise Exception(f"Tried to run {self.hook_module}.ready() but its already been called!")

        settings.HOOKS[self.id]._is_ready = True
