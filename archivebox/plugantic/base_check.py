from typing import List, Type, Any

from pydantic_core import core_schema
from pydantic import GetCoreSchemaHandler, BaseModel

from django.utils.functional import classproperty
from django.core.checks import Warning, Tags, register

class BaseCheck:
    label: str = ''
    tag: str = Tags.database
    
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.typed_dict_schema(
            {
                'name': core_schema.typed_dict_field(core_schema.str_schema()),
                'tag': core_schema.typed_dict_field(core_schema.str_schema()),
            },
        )


    @classproperty
    def name(cls) -> str:
        return cls.label or cls.__name__
    
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
        # Regsiter in ArchiveBox plugins runtime settings
        self._plugin = parent_plugin
        settings.CHECKS[self.name] = self

        # Register using Django check framework
        def run_check(app_configs, **kwargs) -> List[Warning]:
            from django.conf import settings
            import logging
            settings = settings
            logger = logging.getLogger('checks')
            return self.check(settings, logger)

        run_check.__name__ = self.label or self.__class__.__name__
        run_check.tags = [self.tag]
        register(self.tag)(run_check)
