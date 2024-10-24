__package__ = 'abx.archivebox'

import importlib
from typing import Dict, Set, Any, TYPE_CHECKING

from benedict import benedict

import abx
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

def get_PLUGIN(plugin_id: str) -> Dict[str, Any]:
    plugin_info = get_PLUGINS().get(plugin_id, {})
    package = plugin_info.get('package', plugin_info.get('PACKAGE', None))
    if not package:
        return {'id': plugin_id, 'hooks': {}}
    module = importlib.import_module(package)
    hooks = abx.get_plugin_hooks(module.__package__)
    assert plugin_info and (plugin_info.get('id') or plugin_info.get('ID') or hooks)
    
    return benedict({
        'id': plugin_id,
        'label': getattr(module, '__label__', plugin_id),
        'module': module,
        'package': module.__package__,
        'hooks': hooks,
        'version': getattr(module, '__version__', '999.999.999'),
        'author': getattr(module, '__author__', 'Unknown'),
        'homepage': getattr(module, '__homepage__', 'https://github.com/ArchiveBox/ArchiveBox'),
        'dependencies': getattr(module, '__dependencies__', []),
        'source_code': module.__file__,
        **plugin_info,
    })
    

def get_HOOKS() -> Set[str]:
    return {
        hook_name
        for plugin_id in get_PLUGINS().keys()
            for hook_name in get_PLUGIN(plugin_id).hooks
    }

def get_CONFIGS() -> benedict:   # Dict[str, 'BaseConfigSet']
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
        'env': env,
        'apt': apt,
        'brew': brew,
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



def get_scope_config(defaults: benedict | None = None, persona=None, seed=None, crawl=None, snapshot=None, archiveresult=None, extra_config=None):
    """Get all the relevant config for the given scope, in correct precedence order"""
    
    from django.conf import settings
    default_config: benedict = defaults or settings.CONFIG
    
    snapshot = snapshot or (archiveresult and archiveresult.snapshot)
    crawl = crawl or (snapshot and snapshot.crawl)
    seed = seed or (crawl and crawl.seed)
    persona = persona or (crawl and crawl.persona)
    
    persona_config = persona.config if persona else {}
    seed_config = seed.config if seed else {}
    crawl_config = crawl.config if crawl else {}
    snapshot_config = snapshot.config if snapshot else {}
    archiveresult_config = archiveresult.config if archiveresult else {}
    extra_config = extra_config or {}
    
    return {
        **default_config,               # defaults / config file / environment variables
        **persona_config,               # lowest precedence
        **seed_config,
        **crawl_config,
        **snapshot_config,
        **archiveresult_config,
        **extra_config,                 # highest precedence
    }
