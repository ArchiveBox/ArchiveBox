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

        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        assert json.dumps(self.model_json_schema(), indent=4), f'Hook {self.name} has invalid JSON schema.'

        self._plugin = parent_plugin         # for debugging only, never rely on this!

        # record installed hook in settings.HOOKS
        settings.HOOKS[self.name] = self

        hook_prefix, plugin_shortname = self.name.split('.', 1)

        print('REGISTERED HOOK:', self.name)
