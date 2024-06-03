__package__ = 'archivebox.plugantic'

from typing import List
from typing_extensions import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    validate_call,
    SerializeAsAny,
)

from .binaries import (
    Binary,
    PythonBinary,
    SqliteBinary,
    DjangoBinary,
    WgetBinary,
    YtdlpBinary,
)
from .extractors import (
    Extractor,
    YtdlpExtractor,
    WgetExtractor,
    WarcExtractor,
)
from .replayers import (
    Replayer,
    GENERIC_REPLAYER,
    MEDIA_REPLAYER,
)
from .configs import (
    ConfigSet,
    WGET_CONFIG,
)


class Plugin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra='ignore', populate_by_name=True)

    name: str = Field(default='baseplugin')                   # e.g. media
    description: str = Field(default='')                      # e.g. get media using yt-dlp
    
    configs: List[SerializeAsAny[ConfigSet]] = Field(default=[])
    binaries: List[SerializeAsAny[Binary]] = Field(default=[])                # e.g. [Binary(name='yt-dlp')]
    extractors: List[SerializeAsAny[Extractor]] = Field(default=[])
    replayers: List[SerializeAsAny[Replayer]] = Field(default=[])

    @model_validator(mode='after')
    def validate(self):
        self.description = self.description or self.name

    @validate_call
    def install(self) -> Self:
        new_binaries = []
        for idx, binary in enumerate(self.binaries):
            new_binaries.append(binary.install() or binary)
        return self.model_copy(update={
            'binaries': new_binaries,
        })

    @validate_call
    def load(self, cache=True) -> Self:
        new_binaries = []
        for idx, binary in enumerate(self.binaries):
            new_binaries.append(binary.load(cache=cache) or binary)
        return self.model_copy(update={
            'binaries': new_binaries,
        })

    @validate_call
    def load_or_install(self, cache=True) -> Self:
        new_binaries = []
        for idx, binary in enumerate(self.binaries):
            new_binaries.append(binary.load_or_install(cache=cache) or binary)
        return self.model_copy(update={
            'binaries': new_binaries,
        })


class CorePlugin(Plugin):
    name: str = 'core'
    configs: List[SerializeAsAny[ConfigSet]] = []
    binaries: List[SerializeAsAny[Binary]] = [PythonBinary(), SqliteBinary(), DjangoBinary()]
    extractors: List[SerializeAsAny[Extractor]] = []
    replayers: List[SerializeAsAny[Replayer]] = [GENERIC_REPLAYER]

class YtdlpPlugin(Plugin):
    name: str = 'ytdlp'
    configs: List[SerializeAsAny[ConfigSet]] = []
    binaries: List[SerializeAsAny[Binary]] = [YtdlpBinary()]
    extractors: List[SerializeAsAny[Extractor]] = [YtdlpExtractor()]
    replayers: List[SerializeAsAny[Replayer]] = [MEDIA_REPLAYER]

class WgetPlugin(Plugin):
    name: str = 'wget'
    configs: List[SerializeAsAny[ConfigSet]] = [*WGET_CONFIG]
    binaries: List[SerializeAsAny[Binary]] = [WgetBinary()]
    extractors: List[SerializeAsAny[Extractor]] = [WgetExtractor(), WarcExtractor()]


CORE_PLUGIN = CorePlugin()
YTDLP_PLUGIN = YtdlpPlugin()
WGET_PLUGIN = WgetPlugin()
PLUGINS = [
    CORE_PLUGIN,
    YTDLP_PLUGIN,
    WGET_PLUGIN,
]
LOADED_PLUGINS = PLUGINS


import json

for plugin in PLUGINS:
    try:
        json.dumps(plugin.model_json_schema(), indent=4)
        # print(json.dumps(plugin.model_json_schema(), indent=4))
    except Exception as err:
        print(f'Failed to generate JSON schema for {plugin.name}')
        raise

# print('-------------------------------------BEFORE INSTALL---------------------------------')
# for plugin in PLUGINS:
#     print(plugin.model_dump_json(indent=4))
# print('-------------------------------------DURING LOAD/INSTALL---------------------------------')
# for plugin in PLUGINS:
    # LOADED_PLUGINS.append(plugin.install())
# print('-------------------------------------AFTER INSTALL---------------------------------')
# for plugin in LOADED_PLUGINS:
    # print(plugin.model_dump_json(indent=4))

