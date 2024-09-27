__package__ = 'abx.archivebox'

from .. import hookspec


@hookspec
def get_CONFIGS():
    return {}

@hookspec
def get_EXTRACTORS():
    return {}

@hookspec
def get_REPLAYERS():
    return {}

@hookspec
def get_CHECKS():
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
