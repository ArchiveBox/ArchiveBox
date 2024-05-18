__package__ = 'archivebox.plugantic'


from pydantic import BaseModel

# from .binproviders import LazyImportStr


class Replayer(BaseModel):
    """Describes how to render an ArchiveResult in several contexts"""
    name: str = 'GenericReplayer'
    url_pattern: str = '*'

    row_template: str = 'plugins/generic_replayer/templates/row.html'
    embed_template: str = 'plugins/generic_replayer/templates/embed.html'
    fullpage_template: str = 'plugins/generic_replayer/templates/fullpage.html'

    # row_view: LazyImportStr = 'plugins.generic_replayer.views.row_view'
    # embed_view: LazyImportStr = 'plugins.generic_replayer.views.embed_view'
    # fullpage_view: LazyImportStr = 'plugins.generic_replayer.views.fullpage_view'
    # icon_view: LazyImportStr = 'plugins.generic_replayer.views.get_icon'
    # thumbnail_view: LazyImportStr = 'plugins.generic_replayer.views.get_icon'


GENERIC_REPLAYER = Replayer(name='generic')
MEDIA_REPLAYER = Replayer(name='media')
