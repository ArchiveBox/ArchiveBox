__package__ = 'abx_plugin_wget'

from pathlib import Path

from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import WGET_BINARY
from .wget_util import wget_output_path

class WgetExtractor(BaseExtractor):
    name: ExtractorName = 'wget'
    binary: BinName = WGET_BINARY.name

    def get_output_path(self, snapshot) -> str:
        # wget_index_path = wget_output_path(snapshot.as_link())
        # if wget_index_path:
        #     return Path(wget_index_path)
        return 'wget'

WGET_EXTRACTOR = WgetExtractor()


class WarcExtractor(BaseExtractor):
    name: ExtractorName = 'warc'
    binary: BinName = WGET_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        warc_files = list((Path(snapshot.link_dir) / 'warc').glob('*.warc.gz'))
        if warc_files:
            return sorted(warc_files, key=lambda x: x.stat().st_size, reverse=True)[0]
        return None


WARC_EXTRACTOR = WarcExtractor()

