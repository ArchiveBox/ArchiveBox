__package__ = 'abx.archivebox'

import inspect
from huey.api import TaskWrapper

from pathlib import Path
from typing import Tuple, Literal, ClassVar, get_args
from pydantic import BaseModel, ConfigDict
from django.utils.functional import cached_property

import abx

HookType = Literal['CONFIG', 'BINPROVIDER', 'BINARY', 'EXTRACTOR', 'REPLAYER', 'CHECK', 'ADMINDATAVIEW', 'QUEUE', 'SEARCHBACKEND']
hook_type_names: Tuple[HookType] = get_args(HookType)

class BaseHook(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        from_attributes=True,
        populate_by_name=True,
        validate_defaults=True,
        validate_assignment=False,
        revalidate_instances="subclass-instances",
        ignored_types=(TaskWrapper, cached_property),
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


    @abx.hookimpl
    def register(self, settings):
        """Called when django.apps.AppConfig.ready() is called"""
        
        # print("REGISTERED HOOK:", self.hook_module)
        self._is_registered = True
        

    @abx.hookimpl
    def ready(self):
        """Called when django.apps.AppConfig.ready() is called"""
        
        assert self._is_registered, f"Tried to run {self.hook_module}.ready() but it was never registered!"
       
        # print("READY HOOK:", self.hook_module)
        self._is_ready = True
