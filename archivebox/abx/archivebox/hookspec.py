__package__ = 'abx.archivebox'

from typing import Dict, Any

from .. import hookspec

from .base_configset import BaseConfigSet

@hookspec
def get_CONFIG() -> BaseConfigSet:
    ...


@hookspec
def get_EXTRACTORS():
    return {}

@hookspec
def get_REPLAYERS():
    return {}

@hookspec
def get_ADMINDATAVIEWS():
    return {}

@hookspec
def get_QUEUES():
    return {}

@hookspec
def get_SEARCHBACKENDS():
    return {}


@hookspec
def extract(snapshot_id) -> Dict[str, Any]:
    return {}
