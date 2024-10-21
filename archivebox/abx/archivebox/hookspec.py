__package__ = 'abx.archivebox'

from typing import Dict, Any

from .. import hookspec

from .base_binary import BaseBinary, BaseBinProvider
from .base_configset import BaseConfigSet
from .base_extractor import BaseExtractor
from .base_searchbackend import BaseSearchBackend


@hookspec
def get_PLUGIN() -> Dict[str, Dict[str, Any]]:
    return {}

@hookspec
def get_CONFIG() -> Dict[str, BaseConfigSet]:
    return {}



@hookspec
def get_EXTRACTORS() -> Dict[str, BaseExtractor]:
    return {}

@hookspec
def get_SEARCHBACKENDS() -> Dict[str, BaseSearchBackend]:
    return {}

# @hookspec
# def get_REPLAYERS() -> Dict[str, BaseReplayer]:
#     return {}

# @hookspec
# def get_ADMINDATAVIEWS():
#     return {}

# @hookspec
# def get_QUEUES():
#     return {}


##############################################################
# provided by abx.pydantic_pkgr.hookspec:
# @hookspec
# def get_BINARIES() -> Dict[str, BaseBinary]:
#     return {}

# @hookspec
# def get_BINPROVIDERS() -> Dict[str, BaseBinProvider]:
#     return {}
