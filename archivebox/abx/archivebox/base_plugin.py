__package__ = 'abx.archivebox'

import abx
import inspect
from pathlib import Path

from django.apps import AppConfig

from typing import List, Type, Dict
from typing_extensions import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    InstanceOf,
    computed_field,
)
from benedict import benedict

from .base_hook import BaseHook, HookType

class BasePlugin(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        arbitrary_types_allowed=True,
        populate_by_name=True,
        from_attributes=True,
        validate_defaults=False,
        validate_assignment=False,
        revalidate_instances="always",
        # frozen=True,
    )

    # Required by AppConfig:
    app_label: str = Field()                      # e.g. 'singlefile'                  (one-word machine-readable representation, to use as url-safe id/db-table prefix_/attr name)
    verbose_name: str = Field()                   # e.g. 'SingleFile'                  (human-readable *short* label, for use in column names, form labels, etc.)
    docs_url: str = Field(default=None)           # e.g. 'https://github.com/...'
    
    # All the hooks the plugin will install:
    hooks: List[InstanceOf[BaseHook]] = Field(default=[])
    
    _is_registered: bool = False
    _is_ready: bool = False
    
    @computed_field
    @property
    def id(self) -> str:
        return self.__class__.__name__
    
    @property
    def name(self) -> str:
        return self.app_label
    
    # @computed_field
    @property
    def plugin_module(self) -> str:  # DottedImportPath
        """ "
        Dotted import path of the plugin's module (after its loaded via settings.INSTALLED_APPS).
        e.g. 'archivebox.plugins_pkg.npm.apps.NpmPlugin' -> 'plugins_pkg.npm'
        """
        return f"{self.__module__}.{self.__class__.__name__}".split("archivebox.", 1)[-1].rsplit('.apps.', 1)[0]


    @property
    def plugin_module_full(self) -> str:  # DottedImportPath
        """e.g. 'archivebox.plugins_pkg.npm.apps.NpmPlugin'"""
        return f"{self.__module__}.{self.__class__.__name__}"
    
    # @computed_field
    @property
    def plugin_dir(self) -> Path:
        return Path(inspect.getfile(self.__class__)).parent.resolve()
    
    @model_validator(mode='after')
    def validate(self) -> Self:
        """Validate the plugin's build-time configuration here before it's registered in Django at runtime."""
        
        # VERY IMPORTANT:
        # preserve references to original default objects,
        # pydantic deepcopies them by default which breaks mutability
        # see https://github.com/pydantic/pydantic/issues/7608
        # if we dont do this, then plugins_extractor.SINGLEFILE_CONFIG != settings.CONFIGS.SingleFileConfig for example
        # and calling .__init__() on one of them will not update the other
        self.hooks = self.model_fields['hooks'].default
        
        assert self.app_label and self.app_label and self.verbose_name, f'{self.__class__.__name__} is missing .name or .app_label or .verbose_name'
        
        # assert json.dumps(self.model_json_schema(), indent=4), f"Plugin {self.plugin_module} has invalid JSON schema."
        
        return self
    
    @property
    def AppConfig(plugin_self) -> Type[AppConfig]:
        """Generate a Django AppConfig class for this plugin."""


        class PluginAppConfig(AppConfig):
            """Django AppConfig for plugin, allows it to be loaded as a Django app listed in settings.INSTALLED_APPS."""
            name = plugin_self.plugin_module
            app_label = plugin_self.app_label
            verbose_name = plugin_self.verbose_name

            default_auto_field = 'django.db.models.AutoField'

            # handled by abx.hookimpl  ready()
            # def ready(self):
            #     from django.conf import settings
            #     plugin_self.ready(settings)

        return PluginAppConfig

    @property
    def HOOKS_BY_ID(self) -> Dict[str, InstanceOf[BaseHook]]:
        return benedict({hook.id: hook for hook in self.hooks})

    @property
    def HOOKS_BY_TYPE(self) -> Dict[HookType, Dict[str, InstanceOf[BaseHook]]]:
        hooks = benedict({})
        for hook in self.hooks:
            hooks[hook.hook_type] = hooks.get(hook.hook_type) or benedict({})
            hooks[hook.hook_type][hook.id] = hook
        return hooks



    @abx.hookimpl
    def register(self, settings):
        from archivebox.config.legacy import bump_startup_progress_bar

        self._is_registered = True
        bump_startup_progress_bar()

        # print('◣----------------- REGISTERED PLUGIN:', self.plugin_module, '-----------------◢')
        # print()

    @abx.hookimpl
    def ready(self, settings=None):
        """Runs any runtime code needed when AppConfig.ready() is called (after all models are imported)."""

        from archivebox.config.legacy import bump_startup_progress_bar

        assert self._is_registered, f"Tried to run {self.plugin_module}.ready() but it was never registered!"
        self._is_ready = True

        # settings.PLUGINS[self.id]._is_ready = True
        bump_startup_progress_bar()


    @abx.hookimpl
    def get_INSTALLED_APPS(self):
        return [self.plugin_module]

