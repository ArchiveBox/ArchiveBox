__package__ = 'archivebox.plugantic'

from typing import Optional, List, Literal, Annotated, Dict, Any
from typing_extensions import Self

from abc import ABC
from pathlib import Path

from pydantic import BaseModel, model_validator, field_serializer, AfterValidator

from .binaries import (
    Binary,
    YtdlpBinary,
    WgetBinary,
)


# stubs
class Snapshot:
    pass

class ArchiveResult:
    pass

def get_wget_output_path(*args, **kwargs) -> Path:
    return Path('.').resolve()



def no_empty_args(args: List[str]) -> List[str]:
    assert all(len(arg) for arg in args)
    return args

ExtractorName = Literal['wget', 'warc', 'media']

HandlerFuncStr = Annotated[str, AfterValidator(lambda s: s.startswith('self.'))]
CmdArgsList = Annotated[List[str], AfterValidator(no_empty_args)]


class Extractor(ABC, BaseModel):
    name: ExtractorName
    binary: Binary

    output_path_func: HandlerFuncStr = 'self.get_output_path'
    should_extract_func: HandlerFuncStr = 'self.should_extract'
    extract_func: HandlerFuncStr = 'self.extract'
    exec_func: HandlerFuncStr = 'self.exec'

    default_args: CmdArgsList = []
    extra_args: CmdArgsList = []
    args: Optional[CmdArgsList] = None

    @model_validator(mode='after')
    def validate_model(self) -> Self:
        if self.args is None:
            self.args = [*self.default_args, *self.extra_args]
        return self

    @field_serializer('binary', when_used='json')
    def dump_binary(binary) -> str:
        return binary.name

    def get_output_path(self, snapshot) -> Path:
        return Path(self.name)

    def should_extract(self, snapshot) -> bool:
        output_dir = self.get_output_path(snapshot)
        if output_dir.glob('*.*'):
            return False
        return True


    def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        output_dir = self.get_output_path(url, **kwargs)

        cmd = [url, *self.args] if self.args is not None else [url, *self.default_args, *self.extra_args]
        proc = self.exec(cmd, pwd=output_dir)

        return {
            'status': 'succeeded' if proc.returncode == 0 else 'failed',
            'output': proc.stdout.decode().strip().split('\n')[-1],
            'output_files': list(output_dir.glob('*.*')),

            'stdout': proc.stdout.decode().strip(),
            'stderr': proc.stderr.decode().strip(),
            'returncode': proc.returncode,
        }

    def exec(self, args: CmdArgsList, pwd: Optional[Path]=None):
        pwd = pwd or Path('.')
        assert self.binary.loaded_provider
        return self.binary.exec(args, pwd=pwd)


class YtdlpExtractor(Extractor):
    name: ExtractorName = 'media'
    binary: Binary = YtdlpBinary()

    def get_output_path(self, snapshot) -> Path:
        return Path(self.name)


class WgetExtractor(Extractor):
    name: ExtractorName = 'wget'
    binary: Binary = WgetBinary()

    def get_output_path(self, snapshot) -> Path:
        return get_wget_output_path(snapshot)


class WarcExtractor(Extractor):
    name: ExtractorName = 'warc'
    binary: Binary = WgetBinary()

    def get_output_path(self, snapshot) -> Path:
        return get_wget_output_path(snapshot)


