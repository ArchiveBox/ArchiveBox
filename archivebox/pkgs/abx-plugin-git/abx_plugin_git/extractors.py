__package__ = 'abx_plugin_git'


from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import GIT_BINARY


class GitExtractor(BaseExtractor):
    name: ExtractorName = 'git'
    binary: BinName = GIT_BINARY.name

    def get_output_path(self, snapshot) -> str:
        return 'git'

GIT_EXTRACTOR = GitExtractor()
