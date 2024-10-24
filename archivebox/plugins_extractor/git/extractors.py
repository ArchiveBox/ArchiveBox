__package__ = 'plugins_extractor.git'

from pathlib import Path

from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from .binaries import GIT_BINARY


class GitExtractor(BaseExtractor):
    name: ExtractorName = 'git'
    binary: str = GIT_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.as_link() / 'git'

GIT_EXTRACTOR = GitExtractor()
