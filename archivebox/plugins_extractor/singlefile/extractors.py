__package__ = 'plugins_extractor.singlefile'

from pathlib import Path

from pydantic_pkgr import BinName
from abx.archivebox.base_extractor import BaseExtractor

from .binaries import SINGLEFILE_BINARY


class SinglefileExtractor(BaseExtractor):
    name: str = 'singlefile'
    binary: BinName = SINGLEFILE_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'singlefile.html'


SINGLEFILE_EXTRACTOR = SinglefileExtractor()
