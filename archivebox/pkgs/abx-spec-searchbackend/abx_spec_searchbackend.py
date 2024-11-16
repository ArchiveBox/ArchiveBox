import abc
from typing import Iterable, List, Dict, cast

import abx
from abx_spec_config import ConfigPluginSpec


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


class SearchBackendPluginSpec:
    __order__ = 10
    
    @staticmethod
    @abx.hookspec
    @abx.hookimpl
    def get_SEARCHBACKENDS() -> Dict[abx.PluginId, BaseSearchBackend]:
        return {}


class ExpectedPluginSpec(SearchBackendPluginSpec, ConfigPluginSpec):
    pass

PLUGIN_SPEC = SearchBackendPluginSpec

TypedPluginManager = abx.ABXPluginManager[ExpectedPluginSpec]
pm = cast(TypedPluginManager, abx.pm)
