__package__ = 'abx_plugin_git'

from pathlib import Path


from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import GIT_BINARY


class GitExtractor(BaseExtractor):
    name: ExtractorName = 'git'
    binary: BinName = GIT_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.as_link() / 'git'

GIT_EXTRACTOR = GitExtractor()
