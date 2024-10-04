__package__ = 'abx.archivebox'

import os
from pathlib import Path
from typing import Type, Tuple, Callable, ClassVar

from benedict import benedict
from pydantic import model_validator, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from pydantic_settings.sources import TomlConfigSettingsSource

from pydantic_pkgr.base_types import func_takes_args_or_kwargs

import abx

from .base_hook import BaseHook, HookType
from . import toml_util


PACKAGE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getcwd()).resolve()



class FlatTomlConfigSettingsSource(TomlConfigSettingsSource):
    """
    A source class that loads variables from a TOML file
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        toml_file: Path | None=None,
    ):
        self.toml_file_path = toml_file or settings_cls.model_config.get("toml_file")
        
        self.nested_toml_data = self._read_files(self.toml_file_path)
        self.toml_data = {}
        for top_level_key, top_level_value in self.nested_toml_data.items():
            if isinstance(top_level_value, dict):
                # value is nested, flatten it
                for key, value in top_level_value.items():
                    self.toml_data[key] = value
            else:
                # value is already flat, just set it as-is
                self.toml_data[top_level_key] = top_level_value
                
        # filter toml_data to only include keys that are defined on this settings_cls
        self.toml_data = {
            key: value
            for key, value in self.toml_data.items()
            if key in settings_cls.model_fields
        }
            
        super(TomlConfigSettingsSource, self).__init__(settings_cls, self.toml_data)


class ArchiveBoxBaseConfig(BaseSettings):
    """
    This is the base class for an ArchiveBox ConfigSet.
    It handles loading values from schema defaults, ArchiveBox.conf TOML config, and environment variables.

    class WgetConfig(ArchiveBoxBaseConfig):
        WGET_BINARY: str = Field(default='wget', alias='WGET_BINARY_PATH')

    c = WgetConfig()
    print(c.WGET_BINARY)                    # outputs: wget

    # you can mutate process environment variable and reload config using .__init__()
    os.environ['WGET_BINARY_PATH'] = 'wget2'
    c.__init__()

    print(c.WGET_BINARY)                    # outputs: wget2

    """
    
    # these pydantic config options are all VERY carefully chosen, make sure to test thoroughly before changing!!!
    model_config = SettingsConfigDict(
        validate_default=False,
        case_sensitive=True,
        extra="ignore",
        arbitrary_types_allowed=False,
        populate_by_name=True,
        from_attributes=True,
        loc_by_alias=False,
        validate_assignment=True,
        validate_return=True,
        revalidate_instances="always",
    )
    
    load_from_defaults: ClassVar[bool] = True
    load_from_configfile: ClassVar[bool] = True
    load_from_environment: ClassVar[bool] = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Defines the config precedence order: Schema defaults -> ArchiveBox.conf (TOML) -> Environment variables"""
        
        ARCHIVEBOX_CONFIG_FILE = DATA_DIR / "ArchiveBox.conf"
        ARCHIVEBOX_CONFIG_FILE_BAK = ARCHIVEBOX_CONFIG_FILE.parent / ".ArchiveBox.conf.bak"
        
        # import ipdb; ipdb.set_trace()
        
        precedence_order = {}
        
        # if ArchiveBox.conf does not exist yet, return defaults -> env order
        if not ARCHIVEBOX_CONFIG_FILE.is_file():
            precedence_order = {
                'defaults': init_settings,
                'environment': env_settings,
            }
        
        # if ArchiveBox.conf exists and is in TOML format, return default -> TOML -> env order
        try:
            precedence_order = precedence_order or {
                'defaults': init_settings,
                'configfile': FlatTomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE),
                'environment': env_settings,
            }
        except Exception as err:
            if err.__class__.__name__ != "TOMLDecodeError":
                raise
            # if ArchiveBox.conf exists and is in INI format, convert it then return default -> TOML -> env order

            # Convert ArchiveBox.conf in INI format to TOML and save original to .ArchiveBox.bak
            original_ini = ARCHIVEBOX_CONFIG_FILE.read_text()
            ARCHIVEBOX_CONFIG_FILE_BAK.write_text(original_ini)
            new_toml = toml_util.convert(original_ini)
            ARCHIVEBOX_CONFIG_FILE.write_text(new_toml)

            precedence_order = {
                'defaults': init_settings,
                'configfile': FlatTomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE),
                'environment': env_settings,
            }
            
        if not cls.load_from_environment:
            precedence_order.pop('environment')
        if not cls.load_from_configfile:
            precedence_order.pop('configfile')
        if not cls.load_from_defaults:
            precedence_order.pop('defaults')

        return tuple(precedence_order.values())

    @model_validator(mode="after")
    def fill_defaults(self):
        """Populate any unset values using function provided as their default"""

        for key, field in self.model_fields.items():
            value = getattr(self, key)
            
            if isinstance(value, Callable):
                # if value is a function, execute it to get the actual value, passing existing config as a dict arg if expected
                if func_takes_args_or_kwargs(value):
                    # assemble dict of existing field values to pass to default factory functions
                    config_so_far = benedict(self.model_dump(include=set(self.model_fields.keys()), warnings=False))
                    computed_default = field.default(config_so_far)
                else:
                    # otherwise it's a pure function with no args, just call it
                    computed_default = field.default()

                # coerce/check to make sure default factory return value matches type annotation
                TypeAdapter(field.annotation).validate_python(computed_default)

                # set generated default value as final validated value
                setattr(self, key, computed_default)
        return self
    
    def update_in_place(self, warn=True, **kwargs):
        """
        Update the config with new values. Use this sparingly! We should almost never be updating config at runtime.
        Sets them in the environment so they propagate to spawned subprocesses / across future re-__init__()s and reload from environment

        Example acceptable use case: user config says SEARCH_BACKEND_ENGINE=sonic but sonic_client pip library is not installed so we cannot use it.
        SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep') can be used to reset it back to ripgrep so we can continue.
        """
        if warn:
            print('[!] WARNING: Some of the provided user config values cannot be used, temporarily ignoring them:')
        for key, value in kwargs.items():
            os.environ[key] = str(value)
            original_value = getattr(self, key)
            if warn:
                print(f'    {key}={original_value} -> {value}')
        self.__init__()
        return self
    
    def as_legacy_config_schema(self):
        # shim for backwards compatibility with old config schema style
        model_values = self.model_dump()
        return benedict({
            key: {'type': field.annotation, 'default': model_values[key]}
            for key, field in self.model_fields.items()
        })


class BaseConfigSet(ArchiveBoxBaseConfig, BaseHook):      # type: ignore[type-arg]
    hook_type: ClassVar[HookType] = 'CONFIG'

    # @abx.hookimpl
    # def ready(self, settings):
    #    # reload config from environment, in case it's been changed by any other plugins
    #    self.__init__()


    @abx.hookimpl
    def get_CONFIGS(self):
        try:
            return {self.id: self}
        except Exception as e:
            # raise Exception(f'Error computing CONFIGS for {type(self)}: {e.__class__.__name__}: {e}')
            print(f'Error computing CONFIGS for {type(self)}: {e.__class__.__name__}: {e}')
        return {}

    @abx.hookimpl
    def get_FLAT_CONFIG(self):
        try:
            return self.model_dump()
        except Exception as e:
            # raise Exception(f'Error computing FLAT_CONFIG for {type(self)}: {e.__class__.__name__}: {e}')
            print(f'Error computing FLAT_CONFIG for {type(self)}: {e.__class__.__name__}: {e}')
        return {}
