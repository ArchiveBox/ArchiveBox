import abc
from typing import Iterable, List, Dict

import abx

@abx.hookspec
@abx.hookimpl
def get_SEARCHBACKENDS() -> Dict[abx.PluginId, 'BaseSearchBackend']:
    return {}


class BaseSearchBackend(abc.ABC):
    name: str

    @staticmethod
    @abc.abstractmethod
    def index(snapshot_id: str, texts: List[str]):
        return

    @staticmethod
    @abc.abstractmethod
    def flush(snapshot_ids: Iterable[str]):
        return

    @staticmethod
    @abc.abstractmethod
    def search(text: str) -> List[str]:
        raise NotImplementedError("search method must be implemented by subclass")

