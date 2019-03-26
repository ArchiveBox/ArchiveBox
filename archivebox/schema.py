from datetime import datetime

from typing import List, Dict, Any, Optional, Union, NamedTuple
from recordclass import RecordClass

Link = Dict[str, Any]

class ArchiveIndex(NamedTuple):
    info: str
    version: str
    source: str
    docs: str
    num_links: int
    updated: str
    links: List[Link]

class ArchiveResult(NamedTuple):
    cmd: List[str]
    pwd: Optional[str]
    cmd_version: Optional[str]
    output: Union[str, Exception, None]
    status: str
    start_ts: datetime
    end_ts: datetime
    duration: int


class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints


class LinkDict(NamedTuple):
    timestamp: str
    url: str
    title: Optional[str]
    tags: str
    sources: List[str]
    history: Dict[str, ArchiveResult]


class RuntimeStats(RecordClass):
    skipped: int
    succeeded: int
    failed: int

    parse_start_ts: datetime
    parse_end_ts: datetime

    index_start_ts: datetime
    index_end_ts: datetime

    archiving_start_ts: datetime
    archiving_end_ts: datetime
