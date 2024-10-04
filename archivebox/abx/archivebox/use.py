__package__ = 'abx.archivebox'

from typing import Dict, Any, TYPE_CHECKING

from django.utils import timezone
from benedict import benedict

from .. import pm

if TYPE_CHECKING:
    from .base_hook import BaseHook
    from .base_configset import BaseConfigSet
    from .base_binary import BaseBinary, BaseBinProvider
    from .base_extractor import BaseExtractor
    from .base_replayer import BaseReplayer
    from .base_check import BaseCheck
    from .base_queue import BaseQueue
    from .base_admindataview import BaseAdminDataView
    from .base_searchbackend import BaseSearchBackend

# API exposed to ArchiveBox code

def get_PLUGINS():
    return benedict({
        plugin.PLUGIN.id: plugin.PLUGIN
        for plugin in pm.get_plugins()
    })

def get_HOOKS(PLUGINS) -> Dict[str, 'BaseHook']:
    return benedict({
        hook.id: hook
        for plugin in PLUGINS.values()
            for hook in plugin.hooks
    })

def get_CONFIGS() -> Dict[str, 'BaseConfigSet']:
    return benedict({
        config_id: config
        for plugin_configs in pm.hook.get_CONFIGS()
            for config_id, config in plugin_configs.items()
    })
    
def get_FLAT_CONFIG() -> Dict[str, Any]:
    return benedict({
        key: value
        for plugin_config_dict in pm.hook.get_FLAT_CONFIG()
            for key, value in plugin_config_dict.items()
    })

def get_BINPROVIDERS() -> Dict[str, 'BaseBinProvider']:
    # TODO: move these to plugins
    from abx.archivebox.base_binary import apt, brew, env
    builtin_binproviders = [apt, brew, env]
    
    return benedict({
        binprovider.id: binprovider
        for plugin_binproviders in [builtin_binproviders, *pm.hook.get_BINPROVIDERS()]
            for binprovider in plugin_binproviders
    })

def get_BINARIES() -> Dict[str, 'BaseBinary']:
    return benedict({
        binary.id: binary
        for plugin_binaries in pm.hook.get_BINARIES()
            for binary in plugin_binaries
    })

def get_EXTRACTORS() -> Dict[str, 'BaseExtractor']:
    return benedict({
        extractor.id: extractor
        for plugin_extractors in pm.hook.get_EXTRACTORS()
            for extractor in plugin_extractors
    })

def get_REPLAYERS() -> Dict[str, 'BaseReplayer']:
    return benedict({
        replayer.id: replayer
        for plugin_replayers in pm.hook.get_REPLAYERS()
            for replayer in plugin_replayers
    })

def get_CHECKS() -> Dict[str, 'BaseCheck']:
    return benedict({
        check.id: check
        for plugin_checks in pm.hook.get_CHECKS()
            for check in plugin_checks
    })

def get_ADMINDATAVIEWS() -> Dict[str, 'BaseAdminDataView']:
    return benedict({
        admin_dataview.id: admin_dataview
        for plugin_admin_dataviews in pm.hook.get_ADMINDATAVIEWS()
            for admin_dataview in plugin_admin_dataviews
    })

def get_QUEUES() -> Dict[str, 'BaseQueue']:
    return benedict({
        queue.id: queue
        for plugin_queues in pm.hook.get_QUEUES()
            for queue in plugin_queues
    })

def get_SEARCHBACKENDS() -> Dict[str, 'BaseSearchBackend']:
    return benedict({
        searchbackend.id: searchbackend
        for plugin_searchbackends in pm.hook.get_SEARCHBACKENDS()
            for searchbackend in plugin_searchbackends
    })


###########################


def register_all_hooks(settings):
    pm.hook.register(settings=settings)



def extract(url_or_snapshot_id):
    from core.models import Snapshot
    
    url, snapshot_abid, snapshot_id = None, None, None
    snapshot = None
    if '://' in url_or_snapshot_id:
        url = url_or_snapshot_id
        try:
            snapshot = Snapshot.objects.get(url=url)
        except Snapshot.DoesNotExist:
            snapshot = Snapshot(url=url_or_snapshot_id, timestamp=str(timezone.now().timestamp()), bookmarked_at=timezone.now())
            snapshot.save()
    elif '-' in url_or_snapshot_id:
        snapshot_id = url_or_snapshot_id
        snapshot = Snapshot.objects.get(id=snapshot_id)
    else:
        snapshot_abid = url_or_snapshot_id
        snapshot = Snapshot.objects.get(abid=snapshot_abid)

    return pm.hook.extract(snapshot_id=snapshot.id)
