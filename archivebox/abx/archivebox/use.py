__package__ = 'abx.archivebox'

import importlib
from typing import Dict, Any, TYPE_CHECKING

from benedict import benedict

from .. import pm

if TYPE_CHECKING:
    from .base_configset import BaseConfigSet
    from .base_binary import BaseBinary, BaseBinProvider
    from .base_extractor import BaseExtractor
    from .base_searchbackend import BaseSearchBackend
    # from .base_replayer import BaseReplayer
    # from .base_queue import BaseQueue
    # from .base_admindataview import BaseAdminDataView

# API exposed to ArchiveBox code

def get_PLUGINS() -> Dict[str, Dict[str, Any]]:
    return benedict({
        plugin_id: plugin
        for plugin_dict in pm.hook.get_PLUGIN()
            for plugin_id, plugin in plugin_dict.items()
    })
    
def get_PLUGIN(plugin_id: str):
    plugin_info = get_PLUGINS().get(plugin_id, {})
    assert plugin_info and getattr(plugin_info, 'PACKAGE', None), f'Plugin {plugin_id} not found'
    
    module = importlib.import_module(plugin_info['PACKAGE'])
    extra_info ={
        'ID': plugin_id,
        'id': plugin_id,
        **plugin_info,
        'SOURCE_PATH': module.__file__,
        'MODULE': module,
        'CONFIG': {},
        'BINARIES': {},
        'BINPROVIDERS': {},
        'EXTRACTORS': {},
        'SEARCHBACKENDS': {},
    }
    try:
        extra_info['CONFIG'] = module.get_CONFIG()[plugin_id]
    except AttributeError:
        pass
    try:
        extra_info['BINARIES'] = module.get_BINARIES()
    except AttributeError:
        pass
    try:
        extra_info['BINPROVIDERS'] = module.get_BINPROVIDERS()
    except AttributeError:
        pass
    try:
        extra_info['EXTRACTORS'] = module.get_EXTRACTORS()
    except AttributeError:
        pass
    try:
        extra_info['SEARCHBACKENDS'] = module.get_SEARCHBACKENDS()
    except AttributeError:
        pass
    return benedict(extra_info)

# def get_HOOKS(PLUGINS) -> Dict[str, 'BaseHook']:
#     return benedict({
#         hook.id: hook
#         for plugin in PLUGINS.values()
#             for hook in plugin.hooks
#     })

def get_CONFIGS() -> Dict[str, 'BaseConfigSet']:
    return benedict({
        config_id: configset
        for plugin_configs in pm.hook.get_CONFIG()
            for config_id, configset in plugin_configs.items()
    })
    
def get_FLAT_CONFIG() -> Dict[str, Any]:
    return benedict({
        key: value
        for configset in get_CONFIGS().values()
            for key, value in configset.model_dump().items()
    })

def get_BINPROVIDERS() -> Dict[str, 'BaseBinProvider']:
    # TODO: move these to plugins
    from abx.archivebox.base_binary import apt, brew, env
    builtin_binproviders = {
        'apt': apt,
        'brew': brew,
        'env': env,
    }
    
    return benedict({
        binprovider_id: binprovider
        for plugin_binproviders in [builtin_binproviders, *pm.hook.get_BINPROVIDERS()]
            for binprovider_id, binprovider in plugin_binproviders.items()
    })

def get_BINARIES() -> Dict[str, 'BaseBinary']:
    return benedict({
        binary_id: binary
        for plugin_binaries in pm.hook.get_BINARIES()
            for binary_id, binary in plugin_binaries.items()
    })

def get_EXTRACTORS() -> Dict[str, 'BaseExtractor']:
    return benedict({
        extractor_id: extractor
        for plugin_extractors in pm.hook.get_EXTRACTORS()
            for extractor_id, extractor in plugin_extractors.items()
    })

# def get_REPLAYERS() -> Dict[str, 'BaseReplayer']:
#     return benedict({
#         replayer.id: replayer
#         for plugin_replayers in pm.hook.get_REPLAYERS()
#             for replayer in plugin_replayers
#     })

# def get_ADMINDATAVIEWS() -> Dict[str, 'BaseAdminDataView']:
#     return benedict({
#         admin_dataview.id: admin_dataview
#         for plugin_admin_dataviews in pm.hook.get_ADMINDATAVIEWS()
#             for admin_dataview in plugin_admin_dataviews
#     })

# def get_QUEUES() -> Dict[str, 'BaseQueue']:
#     return benedict({
#         queue.id: queue
#         for plugin_queues in pm.hook.get_QUEUES()
#             for queue in plugin_queues
#     })

def get_SEARCHBACKENDS() -> Dict[str, 'BaseSearchBackend']:
    return benedict({
        searchbackend_id: searchbackend
        for plugin_searchbackends in pm.hook.get_SEARCHBACKENDS()
            for searchbackend_id,searchbackend in plugin_searchbackends.items()
    })


###########################


# def extract(url_or_snapshot_id):
#     from core.models import Snapshot
    
#     url, snapshot_abid, snapshot_id = None, None, None
#     snapshot = None
#     if '://' in url_or_snapshot_id:
#         url = url_or_snapshot_id
#         try:
#             snapshot = Snapshot.objects.get(url=url)
#         except Snapshot.DoesNotExist:
#             snapshot = Snapshot(url=url_or_snapshot_id, timestamp=str(timezone.now().timestamp()), bookmarked_at=timezone.now())
#             snapshot.save()
#     elif '-' in url_or_snapshot_id:
#         snapshot_id = url_or_snapshot_id
#         snapshot = Snapshot.objects.get(id=snapshot_id)
#     else:
#         snapshot_abid = url_or_snapshot_id
#         snapshot = Snapshot.objects.get(abid=snapshot_abid)

#     return pm.hook.extract(snapshot_id=snapshot.id)
