__package__ = 'archivebox.plugantic'

from typing import Iterable, List
from benedict import benedict
from pydantic import Field


from .base_hook import BaseHook, HookType



class BaseSearchBackend(BaseHook):
    hook_type: HookType = 'SEARCHBACKEND'

    name: str = Field()       # e.g. 'singlefile'

    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        return

    @staticmethod
    def flush(snapshot_ids: Iterable[str]):
        return

    @staticmethod
    def search(text: str) -> List[str]:
        raise NotImplementedError("search method must be implemented by subclass")
    
    
    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        # Install queue into settings.SEARCH_BACKENDS
        settings.SEARCH_BACKENDS = getattr(settings, "SEARCH_BACKENDS", None) or benedict({})
        settings.SEARCH_BACKENDS[self.id] = self

        # Record installed hook into settings.HOOKS
        super().register(settings, parent_plugin=parent_plugin)

