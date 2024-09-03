__package__ = 'archivebox.plugantic'

import json

from django.apps import AppConfig
from django.core.checks import register

from typing import List, ClassVar, Type, Dict
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

from .base_configset import BaseConfigSet
from .base_binary import BaseBinProvider, BaseBinary
from .base_extractor import BaseExtractor
from .base_replayer import BaseReplayer
from .base_check import BaseCheck
from .base_admindataview import BaseAdminDataView

from ..config import ANSI, AttrDict


class BasePlugin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra='ignore', populate_by_name=True)

    # Required by AppConfig:
    name: str = Field()                           # e.g. 'builtin_plugins.singlefile'
    app_label: str = Field()                      # e.g. 'singlefile'
    verbose_name: str = Field()                   # e.g. 'SingleFile'
    default_auto_field: ClassVar[str] = 'django.db.models.AutoField'
    
    # Required by Plugantic:
    configs: List[InstanceOf[BaseConfigSet]] = Field(default=[])
    binproviders: List[InstanceOf[BaseBinProvider]] = Field(default=[])                # e.g. [Binary(name='yt-dlp')]
    binaries: List[InstanceOf[BaseBinary]] = Field(default=[])                # e.g. [Binary(name='yt-dlp')]
    extractors: List[InstanceOf[BaseExtractor]] = Field(default=[])
    replayers: List[InstanceOf[BaseReplayer]] = Field(default=[])
    checks: List[InstanceOf[BaseCheck]] = Field(default=[])
    admindataviews: List[InstanceOf[BaseAdminDataView]] = Field(default=[])

    @model_validator(mode='after')
    def validate(self) -> Self:
        """Validate the plugin's build-time configuration here before it's registered in Django at runtime."""
        
        assert self.name and self.app_label and self.verbose_name, f'{self.__class__.__name__} is missing .name or .app_label or .verbose_name'
        
        assert json.dumps(self.model_json_schema(), indent=4), f'Plugin {self.name} has invalid JSON schema.'
    
    @property
    def AppConfig(plugin_self) -> Type[AppConfig]:
        """Generate a Django AppConfig class for this plugin."""

        class PluginAppConfig(AppConfig):
            name = plugin_self.name
            app_label = plugin_self.app_label
            verbose_name = plugin_self.verbose_name
        
            def ready(self):
                from django.conf import settings
                
                plugin_self.validate()
                plugin_self.register(settings)

        return PluginAppConfig
    
    @computed_field
    @property
    def BINPROVIDERS(self) -> Dict[str, BaseBinProvider]:
        return AttrDict({binprovider.name: binprovider for binprovider in self.binproviders})
    
    @computed_field
    @property
    def BINARIES(self) -> Dict[str, BaseBinary]:
        return AttrDict({binary.python_name: binary for binary in self.binaries})
    
    @computed_field
    @property
    def CONFIGS(self) -> Dict[str, BaseConfigSet]:
        return AttrDict({config.name: config for config in self.configs})
    
    @computed_field
    @property
    def EXTRACTORS(self) -> Dict[str, BaseExtractor]:
        return AttrDict({extractor.name: extractor for extractor in self.extractors})
    
    @computed_field
    @property
    def REPLAYERS(self) -> Dict[str, BaseReplayer]:
        return AttrDict({replayer.name: replayer for replayer in self.replayers})
    
    @computed_field
    @property
    def CHECKS(self) -> Dict[str, BaseCheck]:
        return AttrDict({check.name: check for check in self.checks})
    
    @computed_field
    @property
    def ADMINDATAVIEWS(self) -> Dict[str, BaseCheck]:
        return AttrDict({admindataview.name: admindataview for admindataview in self.admindataviews})
    
    @computed_field
    @property
    def PLUGIN_KEYS(self) -> List[str]:
        return 

    def register(self, settings=None):
        """Loads this plugin's configs, binaries, extractors, and replayers into global Django settings at runtime."""
        
        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        assert all(hasattr(settings, key) for key in ['PLUGINS', 'CONFIGS', 'BINARIES', 'EXTRACTORS', 'REPLAYERS', 'ADMINDATAVIEWS']), 'Tried to register plugin in settings but couldnt find required global dicts in settings.'

        assert json.dumps(self.model_json_schema(), indent=4), f'Plugin {self.name} has invalid JSON schema.'

        assert self.app_label not in settings.PLUGINS, f'Tried to register plugin {self.name} but it conflicts with existing plugin of the same name ({self.app_label}).'

        ### Mutate django.conf.settings... values in-place to include plugin-provided overrides
        settings.PLUGINS[self.app_label] = self

        for config in self.CONFIGS.values():
            config.register(settings, parent_plugin=self)
        
        for binprovider in self.BINPROVIDERS.values():
            binprovider.register(settings, parent_plugin=self)
        
        for binary in self.BINARIES.values():
            binary.register(settings, parent_plugin=self)
        
        for extractor in self.EXTRACTORS.values():
            extractor.register(settings, parent_plugin=self)

        for replayer in self.REPLAYERS.values():
            replayer.register(settings, parent_plugin=self)

        for check in self.CHECKS.values():
            check.register(settings, parent_plugin=self)

        for admindataview in self.ADMINDATAVIEWS.values():
            admindataview.register(settings, parent_plugin=self)

        # TODO: add parsers? custom templates? persona fixtures?

        plugin_prefix, plugin_shortname = self.name.split('.', 1)

        print(
            f'    > {ANSI.black}{plugin_prefix.upper().replace("_PLUGINS", "").ljust(15)} ' +
            f'{ANSI.lightyellow}{plugin_shortname.ljust(12)} ' + 
            f'{ANSI.black}CONFIGSx{len(self.configs)}  BINARIESx{len(self.binaries)}  EXTRACTORSx{len(self.extractors)}  REPLAYERSx{len(self.replayers)}  CHECKSx{len(self.CHECKS)}  ADMINDATAVIEWSx{len(self.ADMINDATAVIEWS)}{ANSI.reset}'
        )

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
        for idx, binary in enumerate(self.binaries):
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
