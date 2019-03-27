import os

from datetime import datetime

from typing import List, Dict, Any, Optional, Union

from dataclasses import dataclass, asdict, field


class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints

LinkDict = Dict[str, Any]

@dataclass(frozen=True)
class ArchiveResult:
    cmd: List[str]
    pwd: Optional[str]
    cmd_version: Optional[str]
    output: Union[str, Exception, None]
    status: str
    start_ts: datetime
    end_ts: datetime
    schema: str = 'ArchiveResult'

    def __post_init__(self):
        assert self.schema == self.__class__.__name__

    def _asdict(self):
        return asdict(self)

    @property
    def duration(self) -> int:
        return (self.end_ts - self.start_ts).seconds

@dataclass(frozen=True)
class Link:
    timestamp: str
    url: str
    title: Optional[str]
    tags: Optional[str]
    sources: List[str]
    history: Dict[str, List[ArchiveResult]] = field(default_factory=lambda: {})
    updated: Optional[datetime] = None
    schema: str = 'Link'

    def __post_init__(self):
        """fix any history result items to be type-checked ArchiveResults"""
        assert self.schema == self.__class__.__name__
        cast_history = {}
        for method, method_history in self.history.items():
            cast_history[method] = []
            for result in method_history:
                if isinstance(result, dict):
                    result = ArchiveResult(**result)
                cast_history[method].append(result)

        object.__setattr__(self, 'history', cast_history)

    def overwrite(self, **kwargs):
        """pure functional version of dict.update that returns a new instance"""
        return Link(**{**self._asdict(), **kwargs})

    def __eq__(self, other):
        if not isinstance(other, Link):
            return NotImplemented
        return self.url == other.url

    def __gt__(self, other):
        if not isinstance(other, Link):
            return NotImplemented
        if not self.timestamp or not other.timestamp:
            return 
        return float(self.timestamp) > float(other.timestamp)
    
    def _asdict(self, extended=False):
        info = {
            'schema': 'Link',
            'url': self.url,
            'title': self.title or None,
            'timestamp': self.timestamp,
            'updated': self.updated or None,
            'tags': self.tags or None,
            'sources': self.sources or [],
            'history': self.history or {},
        }
        if extended:
            info.update({
                'link_dir': self.link_dir,
                'archive_path': self.archive_path,
                'bookmarked_date': self.bookmarked_date,
                'updated_date': self.updated_date,
                'domain': self.domain,
                'path': self.path,
                'basename': self.basename,
                'extension': self.extension,
                'base_url': self.base_url,
                'is_static': self.is_static,
                'is_archived': self.is_archived,
                'num_outputs': self.num_outputs,
                'num_failures': self.num_failures,
                'oldest_archive_date': self.oldest_archive_date,
                'newest_archive_date': self.newest_archive_date,
            })
        return info

    @property
    def link_dir(self) -> str:
        from config import ARCHIVE_DIR
        return os.path.join(ARCHIVE_DIR, self.timestamp)

    @property
    def archive_path(self) -> str:
        from config import ARCHIVE_DIR_NAME
        return '{}/{}'.format(ARCHIVE_DIR_NAME, self.timestamp)
    
    ### URL Helpers
    @property
    def urlhash(self):
        from util import hashurl

        return hashurl(self.url)

    @property
    def extension(self) -> str:
        from util import extension
        return extension(self.url)

    @property
    def domain(self) -> str:
        from util import domain
        return domain(self.url)

    @property
    def path(self) -> str:
        from util import path
        return path(self.url)

    @property
    def basename(self) -> str:
        from util import basename
        return basename(self.url)

    @property
    def base_url(self) -> str:
        from util import base_url
        return base_url(self.url)

    ### Pretty Printing Helpers
    @property
    def bookmarked_date(self) -> Optional[str]:
        from util import ts_to_date
        return ts_to_date(self.timestamp) if self.timestamp else None

    @property
    def updated_date(self) -> Optional[str]:
        from util import ts_to_date
        return ts_to_date(self.updated) if self.updated else None

    @property
    def oldest_archive_date(self) -> Optional[datetime]:
        from util import ts_to_date

        most_recent = min(
            (result.start_ts
             for method in self.history.keys()
                for result in self.history[method]),
            default=None,
        )
        return ts_to_date(most_recent) if most_recent else None

    @property
    def newest_archive_date(self) -> Optional[datetime]:
        from util import ts_to_date

        most_recent = max(
            (result.start_ts
             for method in self.history.keys()
                for result in self.history[method]),
            default=None,
        )
        return ts_to_date(most_recent) if most_recent else None

    ### Archive Status Helpers
    @property
    def num_outputs(self) -> int:
        return len(tuple(filter(None, self.latest_outputs().values())))

    @property
    def num_failures(self) -> int:
        return sum(1
                   for method in self.history.keys()
                       for result in self.history[method]
                            if result.status == 'failed')

    @property
    def is_static(self) -> bool:
        from util import is_static_file
        return is_static_file(self.url)

    @property
    def is_archived(self) -> bool:
        from config import ARCHIVE_DIR
        from util import domain

        return os.path.exists(os.path.join(
            ARCHIVE_DIR,
            self.timestamp,
            domain(self.url),
        ))

    def latest_outputs(self, status: str=None) -> Dict[str, Optional[str]]:
        """get the latest output that each archive method produced for link"""
        
        latest = {
            'title': None,
            'favicon': None,
            'wget': None,
            'warc': None,
            'pdf': None,
            'screenshot': None,
            'dom': None,
            'git': None,
            'media': None,
            'archive_org': None,
        }
        for archive_method in latest.keys():
            # get most recent succesful result in history for each archive method
            history = self.history.get(archive_method) or []
            history = filter(lambda result: result.output, reversed(history))
            if status is not None:
                history = filter(lambda result: result.status == status, history)

            history = list(history)
            if history:
                latest[archive_method] = history[0].output

        return latest

    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        from util import wget_output_path
        canonical = {
            'index_url': 'index.html',
            'favicon_url': 'favicon.ico',
            'google_favicon_url': 'https://www.google.com/s2/favicons?domain={}'.format(self.domain),
            'archive_url': wget_output_path(self),
            'warc_url': 'warc',
            'pdf_url': 'output.pdf',
            'screenshot_url': 'screenshot.png',
            'dom_url': 'output.html',
            'archive_org_url': 'https://web.archive.org/web/{}'.format(self.base_url),
            'git_url': 'git',
            'media_url': 'media',
        }
        if self.is_static:
            # static binary files like PDF and images are handled slightly differently.
            # they're just downloaded once and aren't archived separately multiple times, 
            # so the wget, screenshot, & pdf urls should all point to the same file

            static_url = wget_output_path(self)
            canonical.update({
                'title': self.basename,
                'archive_url': static_url,
                'pdf_url': static_url,
                'screenshot_url': static_url,
                'dom_url': static_url,
            })
        return canonical


@dataclass(frozen=True)
class ArchiveIndex:
    info: str
    version: str
    source: str
    docs: str
    num_links: int
    updated: str
    links: List[Link]
    schema: str = 'ArchiveIndex'

    def __post_init__(self):
        assert self.schema == self.__class__.__name__

    def _asdict(self):
        return asdict(self)

@dataclass
class RuntimeStats:
    """mutable stats counter for logging archiving timing info to CLI output"""

    skipped: int
    succeeded: int
    failed: int

    parse_start_ts: datetime
    parse_end_ts: datetime

    index_start_ts: datetime
    index_end_ts: datetime

    archiving_start_ts: datetime
    archiving_end_ts: datetime
