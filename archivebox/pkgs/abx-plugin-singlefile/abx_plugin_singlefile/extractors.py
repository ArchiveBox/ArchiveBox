__package__ = 'abx_plugin_singlefile'


from pathlib import Path

from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import SINGLEFILE_BINARY


class SinglefileExtractor(BaseExtractor):
    name: ExtractorName = 'singlefile'
    binary: BinName = SINGLEFILE_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'singlefile.html'


SINGLEFILE_EXTRACTOR = SinglefileExtractor()
