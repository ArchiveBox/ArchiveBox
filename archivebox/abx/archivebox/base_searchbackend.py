__package__ = 'abx.archivebox'

from typing import Iterable, List
from pydantic import Field

import abx
from .base_hook import BaseHook, HookType



class BaseSearchBackend(BaseHook):
    hook_type: HookType = 'SEARCHBACKEND'

    name: str = Field()       # e.g. 'singlefile'


    # TODO: move these to a hookimpl

    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        return

    @staticmethod
    def flush(snapshot_ids: Iterable[str]):
        return

    @staticmethod
    def search(text: str) -> List[str]:
        raise NotImplementedError("search method must be implemented by subclass")
    
    @abx.hookimpl
    def get_SEARCHBACKENDS(self):
        return [self]
