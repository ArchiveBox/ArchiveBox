__package__ = 'plugins_extractor.mercury'

from pathlib import Path

from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from .binaries import MERCURY_BINARY



class MercuryExtractor(BaseExtractor):
    name: ExtractorName = 'mercury'
    binary: str = MERCURY_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.link_dir / 'mercury' / 'content.html'


MERCURY_EXTRACTOR = MercuryExtractor()
