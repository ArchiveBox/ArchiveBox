from typing import List, Type, Any, Dict

from pydantic_core import core_schema
from pydantic import GetCoreSchemaHandler, BaseModel

from django.utils.functional import classproperty
from django.core.checks import Warning, Tags, register

class BaseAdminDataView(BaseModel):
    name: str = 'NPM Installed Packages'
    route: str = '/npm/installed/'
    view: str = 'builtin_plugins.npm.admin.installed_list_view'
    items: Dict[str, str] = {
        "name": "installed_npm_pkg",
        'route': '<str:key>/',
        'view': 'builtin_plugins.npm.admin.installed_detail_view',
    }

    def as_route(self) -> Dict[str, str | Dict[str, str]]:
        return {
            'route': self.route,
            'view': self.view,
            'name': self.name,
            'items': self.items,
        }

    def register(self, settings, parent_plugin=None):
        """Regsiter AdminDataViews.as_route() in settings.ADMIN_DATA_VIEWS.URLS at runtime"""
        self._plugin = parent_plugin                          # circular ref to parent only here for easier debugging! never depend on circular backref to parent in real code!

        route = self.as_route()
        if route not in settings.ADMIN_DATA_VIEWS.URLS:
            settings.ADMIN_DATA_VIEWS.URLS += [route]         # append our route (update in place)

