__package__ = 'abx.archivebox'

import abx

from .base_hook import BaseHook, HookType


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

    @abx.hookimpl
    def get_REPLAYERS(self):
        return [self]

    # TODO: add hookimpl methods for get_row_template, get_embed_template, get_fullpage_template, etc...
