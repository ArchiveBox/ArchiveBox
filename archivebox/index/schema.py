"""

WARNING: THIS FILE IS ALL LEGACY CODE TO BE REMOVED.

DO NOT ADD ANY NEW FEATURES TO THIS FILE, NEW CODE GOES HERE: core/models.py

These are the old types we used to use before ArchiveBox v0.4 (before we switched to Django).
"""

__package__ = 'archivebox.index'

from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Union, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, computed_field
from benedict import benedict

from archivebox.config import ARCHIVE_DIR, CONSTANTS
from archivebox.misc.util import parse_date


class ArchiveError(Exception):
    def __init__(self, message, hints=None):
        super().__init__(message)
        self.hints = hints


# Type aliases
LinkDict = Dict[str, Any]
ArchiveOutput = Union[str, Exception, None]

class ArchiveResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    TYPE: str = 'index.schema.ArchiveResult'
    cmd: list[str]
    pwd: str | None = None
    cmd_version: str | None = None
    output: ArchiveOutput | None = None
    status: str
    start_ts: datetime
    end_ts: datetime
    index_texts: list[str] | None = None

    # Class variables for compatibility
    _field_names: ClassVar[list[str] | None] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        if not v:
            raise ValueError('status must be a non-empty string')
        return v

    @field_validator('cmd')
    @classmethod
    def validate_cmd(cls, v: List[str]) -> List[str]:
        if not all(isinstance(arg, str) and arg for arg in v):
            raise ValueError('all command arguments must be non-empty strings')
        return v

    @field_validator('pwd')
    @classmethod
    def validate_pwd(cls, v: Optional[str]) -> Optional[str]:
        if v == '':  # Convert empty string to None for consistency
            return None
        return v

    @field_validator('cmd_version')
    @classmethod
    def validate_cmd_version(cls, v: Optional[str]) -> Optional[str]:
        if v == '':  # Convert empty string to None for consistency
            return None
        return v

    def model_dump(self, **kwargs) -> dict:
        """Backwards compatible with _asdict()"""
        return super().model_dump(**kwargs)

    @classmethod
    def field_names(cls) -> List[str]:
        """Get all field names of the model"""
        if cls._field_names is None:
            cls._field_names = list(cls.model_fields.keys())
        return cls._field_names

    @classmethod
    def guess_ts(cls, dict_info: dict) -> tuple[datetime, datetime]:
        """Guess timestamps from dictionary info"""
        
        parsed_timestamp = parse_date(dict_info["timestamp"])
        start_ts = parsed_timestamp
        end_ts = parsed_timestamp + timedelta(seconds=int(dict_info["duration"]))
        return start_ts, end_ts

    @classmethod
    def from_json(cls, json_info: dict, guess: bool = False) -> 'ArchiveResult':
        """Create instance from JSON data"""
        
        info = {
            key: val
            for key, val in json_info.items()
            if key in cls.field_names()
        }

        if guess:
            if "start_ts" not in info:
                info["start_ts"], info["end_ts"] = cls.guess_ts(json_info)
            else:
                info['start_ts'] = parse_date(info['start_ts'])
                info['end_ts'] = parse_date(info['end_ts'])
            
            if "pwd" not in info:
                info["pwd"] = str(ARCHIVE_DIR / json_info["timestamp"])
            if "cmd_version" not in info:
                info["cmd_version"] = "Undefined"
            if "cmd" not in info:
                info["cmd"] = []
        else:
            info['start_ts'] = parse_date(info['start_ts'])
            info['end_ts'] = parse_date(info['end_ts'])
            info['cmd_version'] = info.get('cmd_version')

        # Handle string command as list
        if isinstance(info.get("cmd"), str):
            info["cmd"] = [info["cmd"]]

        return cls(**info)

    def to_dict(self, *keys: str) -> dict:
        """Convert to dictionary, optionally filtering by keys"""
        data = self.model_dump()
        if keys:
            return {k: v for k, v in data.items() if k in keys}
        return data

    def to_json(self, indent: int = 4, sort_keys: bool = True) -> str:
        """Convert to JSON string"""
        return self.model_dump_json(indent=indent, exclude_none=True)

    def to_csv(self, cols: Optional[List[str]] = None, separator: str = ',', ljust: int = 0) -> str:
        """Convert to CSV string"""
        data = self.model_dump()
        cols = cols or self.field_names()
        return separator.join(str(data.get(col, '')).ljust(ljust) for col in cols)

    @computed_field
    def duration(self) -> int:
        """Calculate duration in seconds between start and end timestamps"""
        return int((self.end_ts - self.start_ts).total_seconds())
    
    


class Link(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    TYPE: str = 'index.schema.Link'
    timestamp: str
    url: str
    title: str | None = None
    tags: str | None = None
    sources: list[str] = Field(default_factory=list)
    history: dict[str, list[ArchiveResult]] = Field(default_factory=dict)
    downloaded_at: datetime | None = None

    # Class variables for compatibility
    _field_names: ClassVar[list[str] | None] = None

    def __str__(self) -> str:
        return f'[{self.timestamp}] {self.url} "{self.title}"'

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Link):
            return NotImplemented
        return self.url == other.url

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Link):
            return NotImplemented
        if not self.timestamp or not other.timestamp:
            return NotImplemented
        return float(self.timestamp) > float(other.timestamp)

    @field_validator('timestamp')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        if not v:
            raise ValueError('timestamp must be a non-empty string')
        if not v.replace('.', '').isdigit():
            raise ValueError('timestamp must be a float str')
        return v

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v or '://' not in v:
            raise ValueError('url must be a valid URL string')
        return v

    @field_validator('title')
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v:
            raise ValueError('title must be a non-empty string if provided')
        return v

    @field_validator('sources')
    @classmethod
    def validate_sources(cls, v: List[str]) -> List[str]:
        if not all(isinstance(source, str) and source for source in v):
            raise ValueError('all sources must be non-empty strings')
        return v

    # Backwards compatibility methods
    def _asdict(self, extended: bool = False) -> dict:
        return benedict(self)

    def overwrite(self, **kwargs) -> 'Link':
        """Pure functional version of dict.update that returns a new instance"""
        current_data = self.model_dump()
        current_data.update(kwargs)
        return Link(**current_data)

    @classmethod
    def field_names(cls) -> list[str]:
        if cls._field_names is None:
            cls._field_names = list(cls.model_fields.keys())
        return cls._field_names

    @classmethod
    def from_json(cls, json_info: dict, guess: bool = False) -> 'Link':
        info = {
            key: val
            for key, val in json_info.items()
            if key in cls.field_names()
        }
        
        # Handle downloaded_at
        info['downloaded_at'] = cls._parse_date(info.get('updated') or info.get('downloaded_at'))
        info['sources'] = info.get('sources') or []

        # Handle history
        json_history = info.get('history') or {}
        cast_history = {}

        for method, method_history in json_history.items():
            cast_history[method] = []
            for json_result in method_history:
                assert isinstance(json_result, dict), 'Items in Link["history"][method] must be dicts'
                cast_result = ArchiveResult.from_json(json_result, guess)
                cast_history[method].append(cast_result)

        info['history'] = cast_history
        return cls(**info)

    def to_json(self, indent: int = 4, sort_keys: bool = True) -> str:
        return self.model_dump_json(indent=indent)

    def to_csv(self, cols: Optional[List[str]] = None, separator: str = ',', ljust: int = 0) -> str:
        data = self.model_dump()
        cols = cols or self.field_names()
        return separator.join(str(data.get(col, '')).ljust(ljust) for col in cols)

    # Properties for compatibility
    @property
    def link_dir(self) -> str:
        return str(ARCHIVE_DIR / self.timestamp)

    @property
    def archive_path(self) -> str:
        return f'{CONSTANTS.ARCHIVE_DIR_NAME}/{self.timestamp}'

    @computed_field
    def bookmarked_date(self) -> Optional[str]:
        max_ts = (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
        if self.timestamp and self.timestamp.replace('.', '').isdigit():
            if 0 < float(self.timestamp) < max_ts:
                return self._ts_to_date_str(datetime.fromtimestamp(float(self.timestamp)))
            return str(self.timestamp)
        return None

    @computed_field
    def downloaded_datestr(self) -> Optional[str]:
        return self._ts_to_date_str(self.downloaded_at) if self.downloaded_at else None

    @property
    def archive_dates(self) -> list[datetime]:
        return [
            self._parse_date(result.start_ts)           # type: ignore
            for results in self.history.values()
            for result in results
        ]

    @property
    def oldest_archive_date(self) -> Optional[datetime]:
        dates = self.archive_dates
        return min(dates) if dates else None

    @property
    def newest_archive_date(self) -> Optional[datetime]:
        dates = self.archive_dates
        return max(dates) if dates else None

    @property
    def num_outputs(self) -> int:
        try:
            return self.as_snapshot().num_outputs
        except Exception:
            return 0

    @property
    def num_failures(self) -> int:
        return sum(
            1 for results in self.history.values() 
                for result in results 
                    if result.status == 'failed')

    def latest_outputs(self, status: Optional[str] = None) -> dict[str, Any]:
        """Get the latest output that each archive method produced for link"""
        ARCHIVE_METHODS = (
            'title', 'favicon', 'wget', 'warc', 'singlefile', 'pdf',
            'screenshot', 'dom', 'git', 'media', 'archive_org',
        )
        latest: Dict[str, Any] = {}
        for archive_method in ARCHIVE_METHODS:
            # get most recent succesful result in history for each archive method
            history = self.history.get(archive_method) or []
            history = list(filter(lambda result: result.output, reversed(history)))
            if status is not None:
                history = list(filter(lambda result: result.status == status, history))

            history = list(history)
            latest[archive_method] = history[0].output if history else None
        return latest

    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        """Predict the expected output paths that should be present after archiving"""
        # You'll need to implement the actual logic based on your requirements
        # TODO: banish this awful duplication from the codebase and import these
        # from their respective extractor files


        from abx_plugin_favicon.config import FAVICON_CONFIG
        canonical = {
            'index_path': 'index.html',
            'favicon_path': 'favicon.ico',
            'google_favicon_path': FAVICON_CONFIG.FAVICON_PROVIDER.format(self.domain),
            'wget_path': f'warc/{self.timestamp}',
            'warc_path': 'warc/',
            'singlefile_path': 'singlefile.html',
            'readability_path': 'readability/content.html',
            'mercury_path': 'mercury/content.html',
            'htmltotext_path': 'htmltotext.txt',
            'pdf_path': 'output.pdf',
            'screenshot_path': 'screenshot.png',
            'dom_path': 'output.html',
            'archive_org_path': f'https://web.archive.org/web/{self.base_url}',
            'git_path': 'git/',
            'media_path': 'media/',
            'headers_path': 'headers.json',
        }
        
        if self.is_static:
            static_path = f'warc/{self.timestamp}'
            canonical.update({
                'title': self.basename,
                'wget_path': static_path,
                'pdf_path': static_path,
                'screenshot_path': static_path,
                'dom_path': static_path,
                'singlefile_path': static_path,
                'readability_path': static_path,
                'mercury_path': static_path,
                'htmltotext_path': static_path,
            })
        return canonical

    # URL helper properties
    @property
    def url_hash(self) -> str:
        # Implement your URL hashing logic here
        from hashlib import sha256
        return sha256(self.url.encode()).hexdigest()[:8]

    @property
    def scheme(self) -> str:
        return self.url.split('://')[0]

    @property
    def domain(self) -> str:
        return self.url.split('://')[1].split('/')[0]

    @property
    def path(self) -> str:
        parts = self.url.split('://', 1)
        return '/' + parts[1].split('/', 1)[1] if len(parts) > 1 and '/' in parts[1] else '/'

    @property
    def basename(self) -> str:
        return self.path.split('/')[-1]

    @property
    def extension(self) -> str:
        basename = self.basename
        return basename.split('.')[-1] if '.' in basename else ''

    @property
    def base_url(self) -> str:
        return f'{self.scheme}://{self.domain}'

    @property
    def is_static(self) -> bool:
        static_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp4', '.mp3', '.wav', '.webm'}
        return any(self.url.lower().endswith(ext) for ext in static_extensions)

    @property
    def is_archived(self) -> bool:
        output_paths = (
            self.domain,
            'output.html',
            'output.pdf',
            'screenshot.png',
            'singlefile.html',
            'readability/content.html',
            'mercury/content.html',
            'htmltotext.txt',
            'media',
            'git',
        )
        return any((Path(ARCHIVE_DIR) / self.timestamp / path).exists() for path in output_paths)

    def as_snapshot(self):
        """Implement this based on your Django model requirements"""
        from core.models import Snapshot
        return Snapshot.objects.get(url=self.url)

    # Helper methods
    @staticmethod
    def _ts_to_date_str(dt: Optional[datetime]) -> Optional[str]:
        return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(date_str))
            except (ValueError, TypeError):
                return None
