__package__ = 'abx_plugin_mercury'

from pathlib import Path

from abx_pkg import BinName
from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import MERCURY_BINARY



class MercuryExtractor(BaseExtractor):
    name: ExtractorName = 'mercury'
    binary: BinName = MERCURY_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.link_dir / 'mercury' / 'content.html'


MERCURY_EXTRACTOR = MercuryExtractor()
