__package__ = 'archivebox.plugantic'

import json
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
    validate_call,
)

from .base_hook import BaseHook, HookType

from ..config import AttrDict


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
        e.g. 'archivebox.builtin_plugins.npm.apps.NpmPlugin' -> 'builtin_plugins.npm'
        """
        return f"{self.__module__}.{self.__class__.__name__}".split("archivebox.", 1)[-1].rsplit('.apps.', 1)[0]

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
        # if we dont do this, then builtin_plugins.base.CORE_CONFIG != settings.CONFIGS.CoreConfig for example
        # and calling .__init__() on one of them will not update the other
        self.hooks = self.model_fields['hooks'].default
        
        assert self.app_label and self.app_label and self.verbose_name, f'{self.__class__.__name__} is missing .name or .app_label or .verbose_name'
        
        assert json.dumps(self.model_json_schema(), indent=4), f"Plugin {self.plugin_module} has invalid JSON schema."
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

            def ready(self):
                from django.conf import settings
                plugin_self.ready(settings)

        return PluginAppConfig

    @property
    def HOOKS_BY_ID(self) -> Dict[str, InstanceOf[BaseHook]]:
        return AttrDict({hook.id: hook for hook in self.hooks})

    @property
    def HOOKS_BY_TYPE(self) -> Dict[HookType, Dict[str, InstanceOf[BaseHook]]]:
        hooks = AttrDict({})
        for hook in self.hooks:
            hooks[hook.hook_type] = hooks.get(hook.hook_type) or AttrDict({})
            hooks[hook.hook_type][hook.id] = hook
        return hooks

    def register(self, settings=None):
        """Loads this plugin's configs, binaries, extractors, and replayers into global Django settings at import time (before models are imported or any AppConfig.ready() are called)."""

        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        assert json.dumps(self.model_json_schema(), indent=4), f'Plugin {self.plugin_module} has invalid JSON schema.'

        assert self.id not in settings.PLUGINS, f'Tried to register plugin {self.plugin_module} but it conflicts with existing plugin of the same name ({self.app_label}).'

        ### Mutate django.conf.settings... values in-place to include plugin-provided overrides
        settings.PLUGINS[self.id] = self

        if settings.PLUGINS[self.id]._is_registered:
            raise Exception(f"Tried to run {self.plugin_module}.register() but its already been called!")

        for hook in self.hooks:
            hook.register(settings, parent_plugin=self)

        settings.PLUGINS[self.id]._is_registered = True
        # print('√ REGISTERED PLUGIN:', self.plugin_module)

    def ready(self, settings=None):
        """Runs any runtime code needed when AppConfig.ready() is called (after all models are imported)."""

        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        assert (
            self.id in settings.PLUGINS and settings.PLUGINS[self.id]._is_registered
        ), f"Tried to run plugin.ready() for {self.plugin_module} but plugin is not yet registered in settings.PLUGINS."

        if settings.PLUGINS[self.id]._is_ready:
            raise Exception(f"Tried to run {self.plugin_module}.ready() but its already been called!")

        for hook in self.hooks:
            hook.ready(settings)
        
        settings.PLUGINS[self.id]._is_ready = True

    # @validate_call
    # def install_binaries(self) -> Self:
    #     new_binaries = []
    #     for idx, binary in enumerate(self.binaries):
    #         new_binaries.append(binary.install() or binary)
    #     return self.model_copy(update={
    #         'binaries': new_binaries,
    #     })

    @validate_call
    def load_binaries(self, cache=True) -> Self:
        new_binaries = []
        for idx, binary in enumerate(self.HOOKS_BY_TYPE['BINARY'].values()):
            new_binaries.append(binary.load(cache=cache) or binary)
        return self.model_copy(update={
            'binaries': new_binaries,
        })

    # @validate_call
    # def load_or_install_binaries(self, cache=True) -> Self:
    #     new_binaries = []
    #     for idx, binary in enumerate(self.binaries):
    #         new_binaries.append(binary.load_or_install(cache=cache) or binary)
    #     return self.model_copy(update={
    #         'binaries': new_binaries,
    #     })




# class YtdlpPlugin(BasePlugin):
#     name: str = 'ytdlp'
#     configs: List[SerializeAsAny[BaseConfigSet]] = []
#     binaries: List[SerializeAsAny[BaseBinary]] = [YtdlpBinary()]
#     extractors: List[SerializeAsAny[BaseExtractor]] = [YtdlpExtractor()]
#     replayers: List[SerializeAsAny[BaseReplayer]] = [MEDIA_REPLAYER]

# class WgetPlugin(BasePlugin):
#     name: str = 'wget'
#     configs: List[SerializeAsAny[BaseConfigSet]] = [*WGET_CONFIG]
#     binaries: List[SerializeAsAny[BaseBinary]] = [WgetBinary()]
#     extractors: List[SerializeAsAny[BaseExtractor]] = [WgetExtractor(), WarcExtractor()]
