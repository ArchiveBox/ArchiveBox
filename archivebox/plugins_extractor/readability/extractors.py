__package__ = 'plugins_extractor.readability'

from pathlib import Path

from pydantic_pkgr import BinName

from abx.archivebox.base_extractor import BaseExtractor

from .binaries import READABILITY_BINARY


class ReadabilityExtractor(BaseExtractor):
    name: str = 'readability'
    binary: BinName = READABILITY_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'readability' / 'content.html'


READABILITY_EXTRACTOR = ReadabilityExtractor()
