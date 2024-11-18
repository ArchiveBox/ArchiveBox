__package__ = 'abx_spec_config'

import os
import sys
import re
from pathlib import Path
from typing import Type, Tuple, Callable, ClassVar, Dict, Any
from typing_extensions import Annotated

import toml
from rich import print

from benedict import benedict
from pydantic import model_validator, TypeAdapter, AliasChoices, AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from pydantic_settings.sources import TomlConfigSettingsSource

import abx

from . import toml_util


AUTOFIXES_HEADER = "[AUTOFIXES]"
AUTOFIXES_SUBHEADER = "# The following config was added automatically to fix problems detected at startup:"

_ALREADY_WARNED_ABOUT_UPDATED_CONFIG = set()

ConfigKeyStr = Annotated[str, AfterValidator(lambda x: x.isidentifier() and x.isupper() and not x.startswith('_'))]


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


class BaseConfigSet(BaseSettings):
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
        revalidate_instances="subclass-instances",
    )
    
    load_from_defaults: ClassVar[bool] = True      # read from schema defaults
    load_from_system: ClassVar[bool] = True        # read from ~/.config/abx/abx.conf
    load_from_collection: ClassVar[bool] = True    # read from ./ArchiveBox.conf
    load_from_environment: ClassVar[bool] = True   # read from environment variables

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
        
        # import ipdb; ipdb.set_trace()
        
        default_configs = [init_settings] if cls.load_from_defaults else []
        system_configs = []
        collection_configs = []
        environment_configs = [env_settings] if cls.load_from_environment else []
        
        # load system config from ~/.config/abx/abx.conf
        SYSTEM_CONFIG_FILE = abx.pm.hook.get_system_config_path()
        if cls.load_from_system and os.path.isfile(SYSTEM_CONFIG_FILE):
            try:
                system_configs = [FlatTomlConfigSettingsSource(settings_cls, toml_file=SYSTEM_CONFIG_FILE)]
            except Exception as err:
                if err.__class__.__name__ == "TOMLDecodeError":
                    convert_ini_to_toml(SYSTEM_CONFIG_FILE)
                    system_configs = [FlatTomlConfigSettingsSource(settings_cls, toml_file=SYSTEM_CONFIG_FILE)]
                else:
                    raise
                
        COLLECTION_CONFIG_FILE = abx.pm.hook.get_collection_config_path()
        if cls.load_from_collection and os.path.isfile(COLLECTION_CONFIG_FILE):
            try:
                collection_configs = [FlatTomlConfigSettingsSource(settings_cls, toml_file=COLLECTION_CONFIG_FILE)]
            except Exception as err:
                if err.__class__.__name__ == "TOMLDecodeError":
                    convert_ini_to_toml(COLLECTION_CONFIG_FILE)
                    collection_configs = [FlatTomlConfigSettingsSource(settings_cls, toml_file=COLLECTION_CONFIG_FILE)]
                else:
                    raise
        
        precedence_order = [
            *default_configs,
            *system_configs,
            *collection_configs,
            *environment_configs,
        ]
        return tuple(precedence_order)

    @model_validator(mode="after")
    def fill_defaults(self):
        """Populate any unset values using function provided as their default"""

        for key in self.model_fields.keys():
            if isinstance(getattr(self, key), Callable):
                if self.load_from_defaults:
                    computed_default = self.get_default_value(key)
                    # set generated default value as final validated value
                    setattr(self, key, computed_default)
        return self
    
    def validate(self):
        """Manual validation method, to be called from plugin/__init__.py:get_CONFIG()"""
        pass
    
    def get_default_value(self, key: ConfigKeyStr):
        """Get the default value for a given config key"""
        field = self.model_fields[key]
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

            return computed_default
        return value
    
    def update_in_place(self, warn=False, persist=False, hint='', **kwargs):
        """
        Update the config with new values. Use this sparingly! We should almost never be updating config at runtime.
        Sets them in the environment so they propagate to spawned subprocesses / across future re-__init__()s and reload from environment

        Example acceptable use case: user config says SEARCH_BACKEND_ENGINE=sonic but sonic_client pip library is not installed so we cannot use it.
        SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep') can be used to reset it back to ripgrep so we can continue.
        """
        
        COLLECTION_CONFIG_FILE = abx.pm.hook.get_collection_config_path()
        # SYSTEM_CONFIG_FILE = abx.pm.hook.get_system_config_path()
        
        # silence warnings if they've already been shown once
        if all(key in _ALREADY_WARNED_ABOUT_UPDATED_CONFIG for key in kwargs.keys()):
            warn = False
        
        if warn or os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes', 'on'):
            fix_scope = 'in ArchiveBox.conf' if persist else 'just for current run'
            print(f'\n[yellow]:warning:  WARNING: Some config cannot be used as-is, fixing automatically {fix_scope}:[/yellow] {hint}', file=sys.stderr)
        
        # set the new values in the environment
        for key, value in kwargs.items():
            os.environ[key] = str(value)
            original_value = getattr(self, key)
            if warn:
                print(f'    {key}={original_value} -> {value}')
                _ALREADY_WARNED_ABOUT_UPDATED_CONFIG.add(key)
        
        # if persist=True, write config changes to data/ArchiveBox.conf [AUTOFIXES] section
        try:
            if persist and COLLECTION_CONFIG_FILE.is_file():
                autofixes_to_add = benedict(kwargs).to_toml(encoder=toml_util.CustomTOMLEncoder())
                
                existing_config = COLLECTION_CONFIG_FILE.read_text().split(AUTOFIXES_HEADER, 1)[0].strip()
                if AUTOFIXES_HEADER in existing_config:
                    existing_autofixes = existing_config.split(AUTOFIXES_HEADER, 1)[-1].strip().replace(AUTOFIXES_SUBHEADER, '').replace(AUTOFIXES_HEADER, '').strip()
                else:
                    existing_autofixes = ''
                
                new_config = '\n'.join(line for line in [
                    existing_config,
                    '\n' + AUTOFIXES_HEADER,
                    AUTOFIXES_SUBHEADER,
                    existing_autofixes,
                    autofixes_to_add,
                ] if line.strip()).strip() + '\n'
                COLLECTION_CONFIG_FILE.write_text(new_config)
        except Exception:
            pass
        self.__init__()
        if warn:
            print(file=sys.stderr)
            
        return self
    
    @property
    def aliases(self) -> Dict[ConfigKeyStr, ConfigKeyStr]:
        alias_map = {}
        for key, field in self.model_fields.items():
            alias_map[key] = key
            
            if field.validation_alias is None:
                continue

            if isinstance(field.validation_alias, AliasChoices):
                for alias in field.validation_alias.choices:
                    alias_map[alias] = key
            elif isinstance(field.alias, str):
                alias_map[field.alias] = key
            else:
                raise ValueError(f'Unknown alias type for field {key}: {field.alias}')
        
        return benedict(alias_map)
    
    
    @property
    def toml_section_header(self):
        """Convert the class name to a TOML section header e.g. ShellConfig -> SHELL_CONFIG"""
        class_name = self.__class__.__name__
        return re.sub('([A-Z]+)', r'_\1', class_name).upper().strip('_')
    
    
    def from_defaults(self) -> Dict[ConfigKeyStr, Any]:
        """Get the dictionary of {key: value} config loaded from the default values"""
        class OnlyDefaultsConfig(self.__class__):
            load_from_defaults = True
            load_from_collection = False
            load_from_environment = False
        return benedict(OnlyDefaultsConfig().model_dump(exclude_unset=False, exclude_defaults=False, exclude=set(self.model_computed_fields.keys())))
    
    def from_collection(self) -> Dict[ConfigKeyStr, Any]:
        """Get the dictionary of {key: value} config loaded from the collection ArchiveBox.conf"""
        class OnlyConfigFileConfig(self.__class__):
            load_from_defaults = False
            load_from_collection = True
            load_from_environment = False
        return benedict(OnlyConfigFileConfig().model_dump(exclude_unset=True, exclude_defaults=False, exclude=set(self.model_computed_fields.keys())))
    
    def from_environment(self) -> Dict[ConfigKeyStr, Any]:
        """Get the dictionary of {key: value} config loaded from the environment variables"""
        class OnlyEnvironmentConfig(self.__class__):
            load_from_defaults = False
            load_from_collection = False
            load_from_environment = True
        return benedict(OnlyEnvironmentConfig().model_dump(exclude_unset=True, exclude_defaults=False, exclude=set(self.model_computed_fields.keys())))
    
    def from_computed(self) -> Dict[ConfigKeyStr, Any]:
        """Get the dictionary of {key: value} config loaded from the computed fields"""
        return benedict(self.model_dump(include=set(self.model_computed_fields.keys())))
    

    def to_toml_dict(self, defaults=False) -> Dict[ConfigKeyStr, Any]:
        """Get the current config as a TOML-ready dict"""
        config_dict = {}
        for key, value in benedict(self).items():
            if defaults or value != self.get_default_value(key):
                config_dict[key] = value
        
        return benedict({self.toml_section_header: config_dict})
    
    def to_toml_str(self, defaults=False) -> str:
        """Get the current config as a TOML string"""
        from archivebox.misc.toml_util import CustomTOMLEncoder
        
        toml_dict = self.to_toml_dict(defaults=defaults)
        if not toml_dict[self.toml_section_header]:
            # if the section is empty, don't write it
            toml_dict.pop(self.toml_section_header)
        
        return toml.dumps(toml_dict, encoder=CustomTOMLEncoder())
    


def func_takes_args_or_kwargs(lambda_func: Callable[..., Any]) -> bool:
    """returns True if a lambda func takes args/kwargs of any kind, otherwise false if it's pure/argless"""
    code = lambda_func.__code__
    has_args = code.co_argcount > 0
    has_varargs = code.co_flags & 0x04 != 0
    has_varkw = code.co_flags & 0x08 != 0
    return has_args or has_varargs or has_varkw




def convert_ini_to_toml(ini_file: Path):
    """Convert an INI file to a TOML file, saving the original to .ORIGINALNAME.bak"""
    
    bak_path = ini_file.parent / f'.{ini_file.name}.bak'
    original_ini = ini_file.read_text()
    bak_path.write_text(original_ini)
    new_toml = toml_util.convert(original_ini)
    ini_file.write_text(new_toml)
