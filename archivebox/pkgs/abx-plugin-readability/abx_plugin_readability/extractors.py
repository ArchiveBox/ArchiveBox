# __package__ = 'abx_plugin_readability'

from pathlib import Path

from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName
from .binaries import READABILITY_BINARY


class ReadabilityExtractor(BaseExtractor):
    name: ExtractorName = 'readability'
    binary: BinName = READABILITY_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'readability' / 'content.html'


READABILITY_EXTRACTOR = ReadabilityExtractor()
