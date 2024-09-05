__package__ = 'archivebox.plugantic'

import json
from typing import Optional, List, Literal, ClassVar
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, computed_field


HookType = Literal['CONFIG', 'BINPROVIDER', 'BINARY', 'EXTRACTOR', 'REPLAYER', 'CHECK', 'ADMINDATAVIEW']
hook_type_names: List[HookType] = ['CONFIG', 'BINPROVIDER', 'BINARY', 'EXTRACTOR', 'REPLAYER', 'CHECK', 'ADMINDATAVIEW']



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

        builtin_plugins.npm.NpmPlugin().AppConfig.ready()                    # called by django
            builtin_plugins.npm.NpmPlugin().register(settings) ->
                builtin_plugins.npm.NpmConfigSet().register(settings)
                    plugantic.base_configset.BaseConfigSet().register(settings)
                        plugantic.base_hook.BaseHook().register(settings, parent_plugin=builtin_plugins.npm.NpmPlugin())

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
        extra='allow',
        arbitrary_types_allowed=True,
        from_attributes=True,
        populate_by_name=True,
        validate_defaults=True,
        validate_assignment=True,
    )

    hook_type: HookType = 'CONFIG'

    @property
    def name(self) -> str:
        return f'{self.__module__}.{__class__.__name__}'

    def register(self, settings, parent_plugin=None):
        """Load a record of an installed hook into global Django settings.HOOKS at runtime."""

        assert json.dumps(self.model_json_schema(), indent=4), f'Hook {self.name} has invalid JSON schema.'

        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        # record installed hook in settings.HOOKS
        self._plugin = parent_plugin         # for debugging only, never rely on this!
        settings.HOOKS[self.name] = self

        print('REGISTERED HOOK:', self.name)
