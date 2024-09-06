__package__ = 'archivebox.plugantic'

from typing import Optional, List, Literal, Annotated, Dict, Any
from typing_extensions import Self

from pathlib import Path

from pydantic import model_validator, AfterValidator
from pydantic_pkgr import BinName

from .base_hook import BaseHook, HookType
from ..config_stubs import AttrDict



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


    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        settings.EXTRACTORS = getattr(settings, "EXTRACTORS", None) or AttrDict({})
        settings.EXTRACTORS[self.id] = self

        super().register(settings, parent_plugin=parent_plugin)



    def get_output_path(self, snapshot) -> Path:
        return Path(self.id.lower())

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

    def exec(self, args: CmdArgsList, pwd: Optional[Path]=None, settings=None):
        pwd = pwd or Path('.')
        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings
        
        binary = settings.BINARIES[self.binary]
        return binary.exec(args, pwd=pwd)


# class YtdlpExtractor(Extractor):
#     name: ExtractorName = 'media'
#     binary: Binary = YtdlpBinary()

#     def get_output_path(self, snapshot) -> Path:
#         return 'media/'


# class WgetExtractor(Extractor):
#     name: ExtractorName = 'wget'
#     binary: Binary = WgetBinary()

#     def get_output_path(self, snapshot) -> Path:
#         return get_wget_output_path(snapshot)


# class WarcExtractor(Extractor):
#     name: ExtractorName = 'warc'
#     binary: Binary = WgetBinary()

#     def get_output_path(self, snapshot) -> Path:
#         return get_wget_output_path(snapshot)


