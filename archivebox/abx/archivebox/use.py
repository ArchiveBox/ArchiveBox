__package__ = 'abx.archivebox'

from benedict import benedict

from .. import pm


# API exposed to ArchiveBox code

def get_PLUGINS():
    return benedict({
        plugin.PLUGIN.id: plugin.PLUGIN
        for plugin in pm.get_plugins()
    })

def get_HOOKS(PLUGINS):
    return benedict({
        hook.id: hook
        for plugin in PLUGINS.values()
            for hook in plugin.hooks
    })

def get_CONFIGS():
    return benedict({
        config_id: config
        for plugin_configs in pm.hook.get_CONFIGS()
            for config_id, config in plugin_configs.items()
    })
    
def get_FLAT_CONFIG():
    return benedict({
        key: value
        for plugin_config_dict in pm.hook.get_FLAT_CONFIG()
            for key, value in plugin_config_dict.items()
    })

def get_BINPROVIDERS():
    return benedict({
        binprovider.id: binprovider
        for plugin_binproviders in pm.hook.get_BINPROVIDERS()
            for binprovider in plugin_binproviders
    })

def get_BINARIES():
    return benedict({
        binary.id: binary
        for plugin_binaries in pm.hook.get_BINARIES()
            for binary in plugin_binaries
    })

def get_EXTRACTORS():
    return benedict({
        extractor.id: extractor
        for plugin_extractors in pm.hook.get_EXTRACTORS()
            for extractor in plugin_extractors
    })

def get_REPLAYERS():
    return benedict({
        replayer.id: replayer
        for plugin_replayers in pm.hook.get_REPLAYERS()
            for replayer in plugin_replayers
    })

def get_CHECKS():
    return benedict({
        check.id: check
        for plugin_checks in pm.hook.get_CHECKS()
            for check in plugin_checks
    })

def get_ADMINDATAVIEWS():
    return benedict({
        admin_dataview.id: admin_dataview
        for plugin_admin_dataviews in pm.hook.get_ADMINDATAVIEWS()
            for admin_dataview in plugin_admin_dataviews
    })

def get_QUEUES():
    return benedict({
        queue.id: queue
        for plugin_queues in pm.hook.get_QUEUES()
            for queue in plugin_queues
    })

def get_SEARCHBACKENDS():
    return benedict({
        searchbackend.id: searchbackend
        for plugin_searchbackends in pm.hook.get_SEARCHBACKENDS()
            for searchbackend in plugin_searchbackends
    })


###########################


def register_all_hooks(settings):
    pm.hook.register(settings=settings)
