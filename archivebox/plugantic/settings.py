import re
import os
import sys
import toml
import json
import platform
import inspect
import tomllib

from typing import Callable, Any, Optional, Pattern, Type, Tuple, Dict, List
from pathlib import Path

from pydantic import BaseModel, Field, FieldValidationInfo, AliasChoices, model_validator, FilePath, DirectoryPath, computed_field, TypeAdapter
from pydantic.fields import FieldInfo

from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from pydantic_settings.sources import InitSettingsSource, ConfigFileSourceMixin, TomlConfigSettingsSource

from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import PydanticOmit, core_schema, to_jsonable_python, ValidationError
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue

import ini_to_toml


class JSONSchemaWithLambdas(GenerateJsonSchema):
    def encode_default(self, default: Any) -> Any:
        """Encode lambda functions in default values properly"""
        config = self._config
        if isinstance(default, Callable):
            return '{{lambda ' + inspect.getsource(default).split('=lambda ')[-1].strip()[:-1] + '}}'
        return to_jsonable_python(
           default,
           timedelta_mode=config.ser_json_timedelta,
           bytes_mode=config.ser_json_bytes,
           serialize_unknown=True
        )

    # for computed_field properties render them like this instead:
    # inspect.getsource(field.wrapped_property.fget).split('def ', 1)[-1].split('\n', 1)[-1].strip().strip('return '),


class ModelWithDefaults(BaseSettings):
    model_config = SettingsConfigDict(validate_default=False, case_sensitive=False, extra='ignore')

    @model_validator(mode='after')
    def fill_defaults(self):
        """Populate any unset values using function provided as their default"""
        for key, field in self.model_fields.items():
            value = getattr(self, key)
            if isinstance(value, Callable):
                # if value is a function, execute it to get the actual value, passing CONFIG dict as an arg
                config_so_far = self.dict(exclude_unset=True)
                fallback_value = field.default(config_so_far)
                
                # check to make sure default factory return value matches type annotation
                TypeAdapter(field.annotation).validate_python(fallback_value)
                
                # set generated default value as final validated value
                setattr(self, key, fallback_value)
        return self

    def as_json(self, model_fields=True, computed_fields=True):
        output_dict = {}
        for section in self.__class__.__mro__[1:]:
            if not section.__name__.isupper():
                break
            output_dict[section.__name__] = output_dict.get(section.__name__) or {}
            include = {}
            if model_fields:
                include.update(**section.model_fields)
            if computed_fields:
                include.update(**section.model_computed_fields)
            output_dict[section.__name__].update(json.loads(section.json(self, include=include)))
        return output_dict

    def as_toml(self, model_fields=True, computed_fields=True):
        output_text = ''
        for section in self.__class__.__mro__[1:]:
            if not section.__name__.isupper():
                break
            include = {}
            if model_fields:
                include.update(**section.model_fields)
            if computed_fields:
                include.update(**section.model_computed_fields)

            output_text += (
                f'[{section.__name__}]\n' + 
                toml.dumps(json.loads(section.json(self, include=include))) + '\n'
            )
        return output_text

    def as_legacy_schema(self, model_fields=True, computed_fields=True):
        """Convert a newer Pydantic Settings BaseModel into the old-style archivebox.config CONFIG_SCHEMA format"""

        schemas = {}
        
        include = {}
        if model_fields:
            include.update(**self.model_fields)
        if computed_fields:
            include.update(**self.model_computed_fields)

        for key, field in include.items():
            key = key.upper()
            defining_class = None
            for cls in self.__class__.__mro__[1:]:
                if key in cls.model_fields or key in cls.model_computed_fields:
                    defining_class = cls
                    break
                
            assert defining_class is not None, f"No defining class found for field {key}! (should be impossible)"

            schemas[defining_class.__name__] = schemas.get(defining_class.__name__) or {}
            schemas[defining_class.__name__][key] = {
                'value': getattr(self, key),
                'type': str(field.annotation.__name__).lower() if hasattr(field, 'annotation') else str(field.return_type).lower(),
                'default': field.default if hasattr(field, 'default') else field.wrapped_property.fget,
                'aliases': (getattr(field.json_schema_extra.get('aliases', {}), 'choices') or []) if getattr(field, 'json_schema_extra') else [],
            }

        return schemas

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        ARCHIVEBOX_CONFIG_FILE = Path('/Users/squash/Local/Code/archiveboxes/ArchiveBox/data/ArchiveBox.conf')
        ARCHIVEBOX_CONFIG_FILE_TOML = ARCHIVEBOX_CONFIG_FILE.parent / f'.ArchiveBox.toml'
        try:
            return (
                init_settings,
                env_settings,
                TomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE),
            )
        except tomllib.TOMLDecodeError:
            toml_str = ini_to_toml.convert(ARCHIVEBOX_CONFIG_FILE.read_text())
            with open(ARCHIVEBOX_CONFIG_FILE_TOML, 'w+') as f:
                f.write(toml_str)

            return (
                init_settings,
                env_settings,
                TomlConfigSettingsSource(settings_cls, toml_file=ARCHIVEBOX_CONFIG_FILE_TOML),
            )


class SHELL_CONFIG(ModelWithDefaults):
    IS_TTY: bool            = Field(default=lambda c: sys.stdout.isatty())
    USE_COLOR: bool         = Field(default=lambda c: c['IS_TTY'])
    SHOW_PROGRESS: bool     = Field(default=lambda c: c['IS_TTY'] and (platform.system() != 'Darwin'))

    IN_DOCKER: bool         = Field(default=False)
    IN_QEMU: bool           = Field(default=False)
    PUID: int               = Field(default=lambda c: os.getuid())
    PGID: int               = Field(default=lambda c: os.getgid())


class GENERAL_CONFIG(ModelWithDefaults):
    # OUTPUT_DIR: DirectoryPath
    CONFIG_FILE: FilePath               = Field(default=lambda c: c['OUTPUT_DIR'] / 'ArchiveBox.conf')

    ONLY_NEW: bool                      = Field(default=True)
    TIMEOUT: int                        = Field(default=60)
    MEDIA_TIMEOUT: int                  = Field(default=3600)
    
    ENFORCE_ATOMIC_WRITES: bool         = Field(default=True)
    OUTPUT_PERMISSIONS: str             = Field(default='644')
    RESTRICT_FILE_NAMES: str            = Field(default='windows')

    URL_DENYLIST: Pattern               = Field(default=re.compile(r'\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$'), aliases=AliasChoices('URL_BLACKLIST'))
    URL_ALLOWLIST: Pattern              = Field(default=re.compile(r''), aliases=AliasChoices('URL_WHITELIST'))
    
    ADMIN_USERNAME: Optional[str]       = Field(default=None, min_length=1, max_length=63, pattern=r'^[\S]+$')
    ADMIN_PASSWORD: Optional[str]       = Field(default=None, min_length=1, max_length=63)
    
    TAG_SEPARATOR_PATTERN: Pattern      = Field(default=re.compile(r'[,]'))

    @computed_field
    @property
    def OUTPUT_DIR(self) -> DirectoryPath:
        return Path('.').resolve()

# class PackageInstalled(ModelWithDefaults):
#     binary_abs: HostBinPathStr
#     version_str: str
#     is_valid: True
#     provider: PackageProvider
#     date_installed: datetime
#     date_checked: datetime

class EntrypointConfig(ModelWithDefaults):
    name: str
    dependency: str
    runtime: Literal['python.eval', 'node.eval', 'puppeteer', 'shell.run', 'ansible']
    CMD: str
    DEFAULT_ARGS: List[str]
    EXTRA_ARGS: List[str]
    ARGS: List[str]
    SCHEMA: EntrypointSchema
    validator: Callable = eval

class VersionEntrypointConfig(ModelWithDefaults):
    DEFAULT_ARGS = ['--version']

class PackageProvider(ModelWithDefaults):
    name: Literal['config', 'PATH', 'pip', 'apt', 'brew', 'npm', 'vendor']

    def install_bin(self, name):
        # ...
        return PackageInstall

    def get_bin_path(self, name, install=True):
        return shell(['which', name])

class DependencyConfig(ModelWithDefaults):
    providers: List[Literal['config', 'PATH', 'pip', 'apt', 'brew', 'npm', 'vendor'], ...]
    name: str
    packages: List[str]
    entrypoints: Dict[str, EntrypointConfig]
    version_cmd: EntrypointConfig = field(default=lambda c: )

class ExtractorConfig(ModelWithDefaults):
    name: str
    description: str = Field(examples=['WGET Extractor'])
    depends_on: DepencencyConfig
    entrypoint: EntrypointConfig = Field(description='Which entrypoint to use for this extractor')

class ReplayerConfig(ModelWithDefaults):
    """Describes how to render an ArchiveResult in several contexts"""
    name: str
    row_template: 'plugins/wget/templates/row.html'
    embed_template: 'plugins/wget/templates/embed.html'
    fullpage_template: 'plugins/wget/templates/fullpage.html'

    icon_view: ImportString 'plugins.wget.replayers.wget.get_icon'
    thumbnail_getter: ImportString = 'plugins.wget.replayers.wget.get_icon'

class PluginConfig(ModelWithDefaults):
    dependencies: Dict[str, DependencyConfig]
    entrypoints: Dict[str, EntrypointConfig]
    extractors: Dict[str, ExtractorConfig]
    replayers: Dict[str, ReplayerConfig]
    
    name: str

    BINARY: 
    PROVIDERS: List[, ...]
    
    ENTRYPOINTS: Dict[str, EntrypointConfig]



    WGET_BINARY: HostBinName = Field(default='wget')

    @computed_field
    @property
    def WGET_PROVIDERS(self) -> List[Provider]:

class WGET_DEPENDENCY_CONFIG(DEPENDENCY_CONFIG):
    pass

class WGET_CONFIG(ModelWithDefaults):
    EXTRACTORS: List[EXTRACTORS] = EXTRACTOR_CONFIG('')
    DEPDENCIES: List[DEPENDENCY_CONFIG] = [DEPENDENCY_CONFIG]

class WgetConfiguration(SingletonModel):
    singleton_instance_id = 1

    dependency_config: WGET_CONFIG = SchemaField()
    extractor_config: WGET_CONFIG = SchemaField()
    replay_config: WGET_CONFIG = SchemaField()
    pkg_config: WGET_CONFIG = SchemaField()





class WGET_CONFIG(ModelWithDefaults):



# class ConfigSet(models.Model):
#     #  scope = when should this config set be active
#     #     host: on a specific host running archivebox
#     #     
#     #     snapshot__added: on or during a specific timeperiod
#     #     user: for actions initiated by a specific archivebox user
#     #     extractor: for specific extractors running under a snapshot
#     #     snapshot_id: for a specific snapshot pk
#     #     snapshot__url: for a specific snapshot url
#     scope = models.CharField(choices=('host', 'date', 'user', 'extractor', 'domain', 'url', 'custom'))
#     lookup = models.CharField(choices=('__eq', '__icontains', '__gte', '__lt', '__startswith', '__endswith', '__in', '__isnull'))
#     match = models.CharField(max_length=128)

#     config = models.JSONField(default={}, schema=Dict[str, JSONValue])
#     getter = models.ImportString(default='django.utils.model_loading.import_string')

#     label = models.CharField(max_length=64)
#     created_by = models.ForeignKey(User, on_delete=models.CASCADE)
#     config = JSONField(schema=Dict[str, JSONValue])



CONFIG_SECTIONS = (GENERAL_CONFIG, SHELL_CONFIG)

class USER_CONFIG(*CONFIG_SECTIONS):
    pass


if __name__ == '__main__':
    # print(ShellConfig(**{'IS_TTY': False, 'PGID': 911}).model_dump())
    # print(json.dumps(SHELL_CONFIG.model_json_schema(schema_generator=JSONSchemaWithLambdas), indent=4))
    # print(json.dumps(GENERAL_CONFIG.model_json_schema(schema_generator=JSONSchemaWithLambdas), indent=4))
    print()
    # os.environ['PGID'] = '422'
    os.environ['URL_ALLOWLIST'] = r'worked!!!!!\\.com'
    config = USER_CONFIG(**{'SHOW_PROGRESS': False, 'ADMIN_USERNAME': 'kip', 'PGID': 911})

    print('==========archivebox.config.CONFIG_SCHEMA======================')
    print(json.dumps(config.as_legacy_schema(), indent=4, default=str))
    
    print('==========JSON=================================================')
    # print(config.__class__.__name__, '=', config.model_dump_json(indent=4))
    print(json.dumps(config.as_json(), indent=4))

    print('==========TOML=================================================')
    print(config.as_toml())


