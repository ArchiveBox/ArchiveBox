__package__ = "archivebox.plugantic"

from typing import List

from django.core.checks import Warning, Tags, register

from .base_hook import BaseHook, HookType
from ..config_stubs import AttrDict

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

        self.register_with_django_check_system(settings)  # (SIDE EFFECT)

        # install hook into settings.CHECKS
        settings.CHECKS = getattr(settings, "CHECKS", None) or AttrDict({})
        settings.CHECKS[self.id] = self

        # record installed hook in settings.HOOKS
        super().register(settings, parent_plugin=parent_plugin)

    def register_with_django_check_system(self, settings):
        def run_check(app_configs, **kwargs) -> List[Warning]:
            import logging
            return self.check(settings, logging.getLogger("checks"))

        run_check.__name__ = self.id
        run_check.tags = [self.tag]
        register(self.tag)(run_check)

