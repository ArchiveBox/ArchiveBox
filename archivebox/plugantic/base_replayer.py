__package__ = 'archivebox.plugantic'


from .base_hook import BaseHook, HookType
from ..config_stubs import AttrDict


class BaseReplayer(BaseHook):
    """Describes how to render an ArchiveResult in several contexts"""
    
    hook_type: HookType = 'REPLAYER'
    
    url_pattern: str = '*'

    row_template: str = 'plugins/generic_replayer/templates/row.html'
    embed_template: str = 'plugins/generic_replayer/templates/embed.html'
    fullpage_template: str = 'plugins/generic_replayer/templates/fullpage.html'

    # row_view: LazyImportStr = 'plugins.generic_replayer.views.row_view'
    # embed_view: LazyImportStr = 'plugins.generic_replayer.views.embed_view'
    # fullpage_view: LazyImportStr = 'plugins.generic_replayer.views.fullpage_view'
    # icon_view: LazyImportStr = 'plugins.generic_replayer.views.get_icon'
    # thumbnail_view: LazyImportStr = 'plugins.generic_replayer.views.get_icon'

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        settings.REPLAYERS = getattr(settings, 'REPLAYERS', None) or AttrDict({})
        settings.REPLAYERS[self.id] = self

        super().register(settings, parent_plugin=parent_plugin)

# class MediaReplayer(BaseReplayer):
#     name: str = 'MediaReplayer'


# MEDIA_REPLAYER = MediaReplayer()
