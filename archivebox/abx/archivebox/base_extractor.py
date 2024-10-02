__package__ = 'abx.archivebox'

import json
import socket
from typing import Optional, List, Literal, Annotated, Dict, Any
from typing_extensions import Self
from pathlib import Path

from pydantic import model_validator, AfterValidator
from pydantic_pkgr import BinName
from django.utils.functional import cached_property

import abx

from .base_hook import BaseHook, HookType
from .base_binary import BaseBinary


def no_empty_args(args: List[str]) -> List[str]:
    assert all(len(arg) for arg in args)
    return args

ExtractorName = Literal['wget', 'warc', 'media', 'singlefile'] | str

HandlerFuncStr = Annotated[str, AfterValidator(lambda s: s.startswith('self.'))]
CmdArgsList = Annotated[List[str], AfterValidator(no_empty_args)]


class BaseExtractor(BaseHook):
    hook_type: HookType = 'EXTRACTOR'
    
    name: ExtractorName
    binary: BinName

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


    def get_output_path(self, snapshot) -> Path:
        return Path(self.id.lower())

    def should_extract(self, snapshot) -> bool:
        try:
            assert self.BIN.version
        except Exception:
            # could not load binary
            return False
        
        # output_dir = self.get_output_path(snapshot)
        # if output_dir.glob('*.*'):
        #     return False
        return True

    @abx.hookimpl
    def extract(self, snapshot_id: str) -> Dict[str, Any]:
        from core.models import Snapshot
        snapshot = Snapshot.objects.get(id=snapshot_id)
        
        if not self.should_extract(snapshot):
            return {}
        
        from archivebox import CONSTANTS
        # output_dir = self.get_output_path(snapshot) or CONSTANTS.TMP_DIR
        output_dir = CONSTANTS.TMP_DIR / 'test'
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [snapshot.url, *self.args] if self.args is not None else [snapshot.url, *self.default_args, *self.extra_args]
        proc = self.exec(cmd, cwd=output_dir)

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        output_json = None
        output_text = stdout
        try:
            output_json = json.loads(stdout.strip())
            output_text = None
        except json.JSONDecodeError:
            pass
        
        errors = []
        if proc.returncode != 0:
            errors.append(f'{self.BIN.name} returned non-zero exit code: {proc.returncode}')   

        # pocket@git+https://github.com/tapanpandita/pocket.git@v0.3.7
        binary_str = f'{self.BIN.abspath}@{self.BIN.binprovider.name}:{self.BIN.binprovider.get_packages(self.BIN.name)}=={self.BIN.version}'

        return {
            'extractor': self.name,
            
            'snapshot_id': snapshot.id,
            'snapshot_abid': snapshot.abid,
            'snapshot_url': snapshot.url,
            'snapshot_created_by_id': snapshot.created_by_id,
            
            'hostname': socket.gethostname(),
            
            'binary': binary_str,
            'binary_name': self.BIN.name,
            'binary_provider': self.BIN.binprovider.name,
            'binary_version': self.BIN.version,
            'binary_abspath': self.BIN.abspath,
            
            'cmd': cmd,
            'stdout': stdout,
            'stderr': stderr,
            'returncode': proc.returncode,
            
            'status': 'succeeded' if proc.returncode == 0 else 'failed',
            'errors': errors,
            'output_dir': str(output_dir.relative_to(CONSTANTS.DATA_DIR)),
            'output_files': list(str(path.relative_to(output_dir)) for path in output_dir.glob('**/*.*')),
            'output_json': output_json or {},
            'output_text': output_text or '',
        }

    # TODO: move this to a hookimpl
    def exec(self, args: CmdArgsList, cwd: Optional[Path]=None, binary=None):
        cwd = cwd or Path('.')
        binary = (binary or self.BINARY).load()
        
        return binary.exec(cmd=args, cwd=cwd)
    
    @cached_property
    def BINARY(self) -> BaseBinary:
        from django.conf import settings
        for binary in settings.BINARIES.values():
            if binary.name == self.binary:
                return binary
        raise ValueError(f'Binary {self.binary} not found')
    
    @cached_property
    def BIN(self) -> BaseBinary:
        return self.BINARY.load()

    @abx.hookimpl
    def get_EXTRACTORS(self):
        return [self]
