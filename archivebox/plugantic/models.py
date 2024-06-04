__package__ = 'archivebox.plugantic'


# import uuid
# from django.db import models
# from typing_extensions import Self

# from django_pydantic_field import SchemaField
# from django.conf import settings

# from abid_utils.models import ABIDModel, ABIDField

# # from .plugins import Plugin as PluginSchema, CORE_PLUGIN
# from .binproviders import BinProvider
# from .binaries import Binary
# from .configs import WgetOptionsConfig
# from .extractors import Extractor
# from .replayers import Replayer


# PLUGINS_ROOT = settings.CONFIG['OUTPUT_DIR'] / 'plugins'
# PLUGINS_ROOT.mkdir(exist_ok=True)


# class CustomPlugin(ABIDModel):
#     abid_prefix = 'plg_'
#     abid_ts_src = 'self.added'
#     abid_uri_src = 'self.name'
#     abid_subtype_src = '"09"'
#     abid_rand_src = 'self.id'

#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # legacy pk
#     uuid = models.UUIDField(blank=True, null=True, editable=True, unique=True)
#     abid = ABIDField(prefix=abid_prefix)

#     name = models.CharField(max_length=64, blank=False, unique=True)

#     path = models.FilePathField(path=str(PLUGINS_ROOT), match='*', recursive=True, allow_folders=True, allow_files=False)

#     # replayers: list[Replayer] = SchemaField()
#     # binaries: list[Replayer] = SchemaField()
#     # extractors: list[Replayer] = SchemaField()


#     # @classmethod
#     # def from_loaded_plugin(cls, plugin: PluginSchema) -> Self:
#     #     new_obj = cls(
#     #         schema=plugin,
#     #     )
#     #     return new_obj
