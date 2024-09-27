__package__ = 'abx.archivebox'

from typing import Dict

import abx

from .base_hook import BaseHook, HookType


class BaseAdminDataView(BaseHook):
    hook_type: HookType = "ADMINDATAVIEW"
    
    name: str = 'example_admin_data_view_list'
    verbose_name: str = 'Data View'
    route: str = '/__OVERRIDE_THIS__/'
    view: str = 'plugins_example.example.views.example_view_list'
    
    items: Dict[str, str] = {
        'route': '<str:key>/',
        "name": 'example_admin_data_view_item',
        'view': 'plugins_example.example.views.example_view_item',
    }
    
    @abx.hookimpl
    def get_ADMINDATAVIEWS(self):
        return [self]
    
    @abx.hookimpl
    def get_ADMIN_DATA_VIEWS_URLS(self):
        """routes to be added to django.conf.settings.ADMIN_DATA_VIEWS['urls']"""
        route = {
            "route": self.route,
            "view": self.view,
            "name": self.verbose_name,
            "items": self.items,
        }
        return [route]

