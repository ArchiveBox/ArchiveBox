__package__ = "abx.archivebox"

from typing import List

from django.core.checks import Warning, Tags, register

import abx

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

    @abx.hookimpl
    def get_CHECKS(self):
        return [self]

    @abx.hookimpl
    def register_checks(self):
        """Tell django that this check exists so it can be run automatically by django."""
        def run_check(**kwargs):
            from django.conf import settings
            import logging
            return self.check(settings, logging.getLogger("checks"))
        
        run_check.__name__ = self.id
        run_check.tags = [self.tag]
        register(self.tag)(run_check)
