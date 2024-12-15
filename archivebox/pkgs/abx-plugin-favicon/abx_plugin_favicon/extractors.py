__package__ = 'abx_plugin_favicon'

from pathlib import Path

from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from abx_plugin_curl.binaries import CURL_BINARY


class FaviconExtractor(BaseExtractor):
    name: ExtractorName = 'favicon'
    binary: BinName = CURL_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return Path(snapshot.link_dir) / 'favicon.png'

FAVICON_EXTRACTOR = FaviconExtractor()
