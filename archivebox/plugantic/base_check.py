__package__ = "archivebox.plugantic"

import abx
from typing import List

from django.core.checks import Warning, Tags, register

from .base_hook import BaseHook, HookType


class BaseCheck(BaseHook):
    hook_type: HookType = "CHECK"
    
    tag: str = Tags.database
    
    @staticmethod
    def check(settings, logger) -> List[Warning]:
        """Override this method to implement your custom runtime check."""
        errors = []
        # if not hasattr(settings, 'SOME_KEY'):
        #     errors.extend(Error(
        #         'Missing settings.SOME_KEY after django_setup(), did SOME_KEY get loaded?',
        #         id='core.C001',
        #         hint='Make sure to run django_setup() is able to load settings.SOME_KEY.',
        #     ))
        # logger.debug('[√] Loaded settings.PLUGINS succesfully.')
        return errors

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin  # backref to parent is for debugging only, never rely on this!

        abx.pm.hook.register_django_check(check=self, settings=settings)



@abx.hookspec
@abx.hookimpl
def register_django_check(check: BaseCheck, settings):
    def run_check(app_configs, **kwargs) -> List[Warning]:
        import logging
        return check.check(settings, logging.getLogger("checks"))

    run_check.__name__ = check.id
    run_check.tags = [check.tag]
    register(check.tag)(run_check)

