__package__ = 'abx.archivebox'

from typing import Iterable, List
import abc



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

