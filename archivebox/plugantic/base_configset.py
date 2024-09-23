__package__ = 'archivebox.plugantic'


from pathlib import Path
from typing import List, Literal, Type, Tuple, Callable, ClassVar

from benedict import benedict
from pydantic import model_validator, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from pydantic_settings.sources import TomlConfigSettingsSource

from django.conf import settings

from .base_hook import BaseHook, HookType
from . import ini_to_toml

ConfigSectionName = Literal[
    'SHELL_CONFIG',
    'GENERAL_CONFIG',
    'SERVER_CONFIG',
    'ARCHIVE_METHOD_TOGGLES',
    'ARCHIVE_METHOD_OPTIONS',
    'SEARCH_BACKEND_CONFIG',
    'DEPENDENCY_CONFIG',
]
ConfigSectionNames: List[ConfigSectionName] = [
    'SHELL_CONFIG',
    'GENERAL_CONFIG',
    'SERVER_CONFIG',
    'ARCHIVE_METHOD_TOGGLES',
    'ARCHIVE_METHOD_OPTIONS',
    'SEARCH_BACKEND_CONFIG',
    'DEPENDENCY_CONFIG',
]

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
        for section_name, section in self.nested_toml_data.items():
            if section_name in ConfigSectionNames and isinstance(section, dict):
                # value is nested, flatten it
                for key, value in section.items():
                    self.toml_data[key] = value
            else:
                # value is already flat, just set it as-is
                self.toml_data[section_name] = section
                
        # filter toml_data to only include keys that are defined on the settings_cls
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
        
        ARCHIVEBOX_CONFIG_FILE = settings.DATA_DIR / "ArchiveBox.conf"
        ARCHIVEBOX_CONFIG_FILE_BAK = ARCHIVEBOX_CONFIG_FILE.parent / ".ArchiveBox.conf.bak"
        
        # import ipdb; ipdb.set_trace()
        
        # if ArchiveBox.conf does not exist yet, return defaults -> env order
        if not ARCHIVEBOX_CONFIG_FILE.is_file():
            return (
                init_settings,
                env_settings,
            )
        
        # if ArchiveBox.conf exists and is in TOML format, return default -> TOML -> env order
        try:
            return (
                init_settings,
                FlatTomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE),
                env_settings,
            )
        except Exception as err:
            if err.__class__.__name__ != "TOMLDecodeError":
                raise
            # if ArchiveBox.conf exists and is in INI format, convert it then return default -> TOML -> env order

            # Convert ArchiveBox.conf in INI format to TOML and save original to .ArchiveBox.bak
            original_ini = ARCHIVEBOX_CONFIG_FILE.read_text()
            ARCHIVEBOX_CONFIG_FILE_BAK.write_text(original_ini)
            new_toml = ini_to_toml.convert(original_ini)
            ARCHIVEBOX_CONFIG_FILE.write_text(new_toml)

            return (
                init_settings,
                FlatTomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE),
                env_settings,
            )

    @model_validator(mode="after")
    def fill_defaults(self):
        """Populate any unset values using function provided as their default"""

        for key, field in self.model_fields.items():
            config_so_far = self.model_dump()
            value = getattr(self, key)
            if isinstance(value, Callable):
                # if value is a function, execute it to get the actual value, passing existing config as a dict arg
                fallback_value = field.default(config_so_far)

                # check to make sure default factory return value matches type annotation
                TypeAdapter(field.annotation).validate_python(fallback_value)

                # set generated default value as final validated value
                setattr(self, key, fallback_value)
        return self

class BaseConfigSet(ArchiveBoxBaseConfig, BaseHook):      # type: ignore[type-arg]
    hook_type: ClassVar[HookType] = 'CONFIG'

    section: ClassVar[ConfigSectionName] = 'GENERAL_CONFIG'

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        settings.FLAT_CONFIG = getattr(settings, "FLAT_CONFIG", None) or benedict({})
        settings.CONFIGS = getattr(settings, "CONFIGS", None) or benedict({})
        
        # pass FLAT_CONFIG so far into our config model to load it
        loaded_config = self.__class__(**settings.FLAT_CONFIG)
        # then dump our parsed config back into FLAT_CONFIG for the next plugin to use
        settings.FLAT_CONFIG.merge(loaded_config.model_dump())
        
        settings.CONFIGS[self.id] = loaded_config

        super().register(settings, parent_plugin=parent_plugin)



# class WgetToggleConfig(ConfigSet):
#     section: ConfigSectionName = 'ARCHIVE_METHOD_TOGGLES'

#     SAVE_WGET: bool = True
#     SAVE_WARC: bool = True

# class WgetDependencyConfig(ConfigSet):
#     section: ConfigSectionName = 'DEPENDENCY_CONFIG'

#     WGET_BINARY: str = Field(default='wget')
#     WGET_ARGS: Optional[List[str]] = Field(default=None)
#     WGET_EXTRA_ARGS: List[str] = []
#     WGET_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

# class WgetOptionsConfig(ConfigSet):
#     section: ConfigSectionName = 'ARCHIVE_METHOD_OPTIONS'

#     # loaded from shared config
#     WGET_AUTO_COMPRESSION: bool = Field(default=True)
#     SAVE_WGET_REQUISITES: bool = Field(default=True)
#     WGET_USER_AGENT: str = Field(default='', alias='USER_AGENT')
#     WGET_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
#     WGET_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
#     WGET_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
#     WGET_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')


# CONFIG = {
#     'CHECK_SSL_VALIDITY': False,
#     'SAVE_WARC': False,
#     'TIMEOUT': 999,
# }


# WGET_CONFIG = [
#     WgetToggleConfig(**CONFIG),
#     WgetDependencyConfig(**CONFIG),
#     WgetOptionsConfig(**CONFIG),
# ]
