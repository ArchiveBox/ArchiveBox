__package__ = 'archivebox.plugantic'

# from typing import Dict

from .base_hook import BaseHook, HookType
from ..config_stubs import AttrDict


class BaseAdminDataView(BaseHook):
    hook_type: HookType = "ADMINDATAVIEW"
    
    # verbose_name: str = 'Data View'
    # route: str = '/npm/installed/'
    # view: str = 'pkg_plugins.npm.admin.installed_list_view'
    # items: Dict[str, str] = {
    #     "name": "installed_npm_pkg",
    #     'route': '<str:key>/',
    #     'view': 'pkg_plugins.npm.admin.installed_detail_view',
    # }

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                          # circular ref to parent only here for easier debugging! never depend on circular backref to parent in real code!

        self.register_route_in_admin_data_view_urls(settings)

        settings.ADMINDATAVIEWS = getattr(settings, "ADMINDATAVIEWS", None) or AttrDict({})
        settings.ADMINDATAVIEWS[self.id] = self

        super().register(settings, parent_plugin)

    def register_route_in_admin_data_view_urls(self, settings):
        route = {
            "route": self.route,
            "view": self.view,
            "name": self.verbose_name,
            "items": self.items,
        }
        if route not in settings.ADMIN_DATA_VIEWS.URLS:
            settings.ADMIN_DATA_VIEWS.URLS += [route]  # append our route (update in place)
