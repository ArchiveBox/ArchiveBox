"""
This file provides the Django ABIDField and ABIDModel base model to inherit from.
"""


from typing import Any, Dict, Union, List, Set, cast

from uuid import uuid4
from functools import partial
from pathlib import Path
from charidfield import CharIDField  # type: ignore[import-untyped]

from django.contrib import admin
from django.core.exceptions import ValidationError, NON_FIELD_ERRORS
from django.db import models
from django.utils import timezone
from django.utils.functional import classproperty
from django.db.utils import OperationalError
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from django.conf import settings
# from django.contrib.contenttypes.models import ContentType
# from django.contrib.contenttypes.fields import GenericForeignKey
# from django.contrib.contenttypes.fields import GenericRelation

from django_stubs_ext.db.models import TypedModelMeta


from archivebox.index.json import to_json

from .abid import (
    ABID,
    ABID_LEN,
    ABID_RAND_LEN,
    ABID_SUFFIX_LEN,
    DEFAULT_ABID_PREFIX,
    DEFAULT_ABID_URI_SALT,
    abid_part_from_prefix,
    abid_hashes_from_values,
    ts_from_abid,
    abid_part_from_ts,
)

####################################################


# Database Field for typeid/ulid style IDs with a prefix, e.g. snp_01BJQMF54D093DXEAWZ6JYRPAQ
ABIDField = partial(
    CharIDField,
    max_length=ABID_LEN,
    help_text="ABID-format identifier for this entity (e.g. snp_01BJQMF54D093DXEAWZ6JYRPAQ)",
    default=None,
    null=True,
    blank=True,
    db_index=True,
    unique=True,
)

def get_or_create_system_user_pk(username='system'):
    """Get or create a system user with is_superuser=True to be the default owner for new DB rows"""

    User = get_user_model()

    # if only one user exists total, return that user
    if User.objects.filter(is_superuser=True).count() == 1:
        return User.objects.filter(is_superuser=True).values_list('pk', flat=True)[0]

    # otherwise, create a dedicated "system" user
    user, _was_created = User.objects.get_or_create(username=username, is_staff=True, is_superuser=True, defaults={'email': '', 'password': ''})
    return user.pk


class AutoDateTimeField(models.DateTimeField):
    # def pre_save(self, model_instance, add):
    #     return timezone.now()
    pass

class ABIDError(Exception):
    pass


# class LabelType:
#     """
#     A Many:1 reference to an object by a human-readable or machine-readable label, e.g.:
#     """
#
#     name: str
#     verbose_name: str
#
# class UUIDLabelType(LabelType):
#     name = 'UUID'
#     verbose_name = 'UUID'
#
# class ABIDLabelType(LabelType):
#     name = 'ABID'
#     verbose_name = 'ABID'
#
# class TimestampLabelType(LabelType):
#     name = 'TIMESTAMP'
#     verbose_name = 'Timestamp'


# class Label(models.Model):
#     """
#     A 1:1 reference to an object by a human-readable or machine-readable label, e.g.:
#
#     Label(label='snp_01BJQMF54D093DXEAWZ6JYRPAQ', content_object=snapshot, reftype='ABID')
#     """
#     class RefTypeChoices(models.TextChoices):
#         UUID = UUIDLabelType.name, UUIDLabelType.verbose_name
#         ABID = ABIDLabelType.name, ABIDLabelType.verbose_name
#         URI = URILabelType.name, URILabelType.verbose_name
#         TAG = TagLabelType.name, TagLabelType.verbose_name
#         TIMESTAMP = TimestampLabelType.name, TimestampLabelType.verbose_name
#
#     id = models.CharField(max_length=255, primary_key=True, null=False, blank=False, db_index=True)
#     reftype = models.CharField(choices=RefTypeChoices.choices, default=RefTypeChoices.ABID, max_length=32)
#
#     content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
#     object_id = models.UUIDField(default=None, null=False, editable=False)
#     content_object = GenericForeignKey("content_type", "object_id")
#
#     @property
#     def created_by(self) -> User:
#         return self.content_object.created_by
#
#     @property
#     def created_by_id(self) -> int:
#         return self.content_object.created_by_id
#
#     @created_by.setter
#     def created_by(self, value: User) -> None:
#         self.content_object.created_by = value
#
#     @created_by_id.setter
#     def created_by_id(self, value: int) -> None:
#         self.content_object.created_by_id = value
#
#     @property
#     def abid_prefix(self) -> str:
#         return self.content_object.abid_prefix
#
#     @property
#     def ABID(self) -> ABID:
#         return ABID.parse(self.abid_prefix + self.abid.split('_', 1)[-1])
#
#     def __str__(self):
#         return self.tag
#
#     class Meta:
#         indexes = [
#             models.Index(fields=["content_type", "object_id"]),
#         ]
#
# class ModelWithLabels(models.Model):
#     labels = GenericRelation(Label)
#
#     def UUID(self) -> uuid4.UUID:
#         return uuid4.UUID(self.labels.filter(reftype=Label.RefTypeChoices.UUID).first().id)
#
#     def ABID(self) -> ABID:
#         return ABID.parse(self.labels.filter(reftype=Label.RefTypeChoices.ABID).first().id)


class ABIDModel(models.Model):
    """
    Abstract Base Model for other models to depend on. Provides ArchiveBox ID (ABID) interface and other helper methods.
    """
    abid_prefix: str = DEFAULT_ABID_PREFIX            # e.g. 'tag_'
    abid_ts_src = 'self.created_at'                  # e.g. 'self.created_at'
    abid_uri_src = 'None'                            # e.g. 'self.uri'                (MUST BE SET)
    abid_subtype_src = 'self.__class__.__name__'     # e.g. 'self.extractor'
    abid_rand_src = 'self.id'                        # e.g. 'self.uuid' or 'self.id'
    abid_salt: str = DEFAULT_ABID_URI_SALT           # combined with self.uri to anonymize hashes on a per-install basis (default is shared globally with all users, means everyone will hash ABC to -> 123 the same around the world, makes it easy to share ABIDs across installs and see if they are for the same URI. Change this if you dont want your hashes to be guessable / in the same hash space as all other users)
    abid_drift_allowed: bool = False                 # set to True to allow abid_field values to change after a fixed ABID has been issued (NOT RECOMMENDED: means values can drift out of sync from original ABID)

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, db_index=True)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    # labels = GenericRelation(Label)
    
    # if ModelWithNotesMixin model:
    #   notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this snapshot should have')
    
    # if StateMachineMixin model:
    #   retry_at = models.DateTimeField(default=None, null=True, db_index=True)
    #   status = models.CharField(max_length=16, choices=StatusChoices.choices, default=StatusChoices.QUEUED)
    #
    #   StatusChoices: ClassVar[Type[DefaultStatusChoices]] = DefaultStatusChoices
    #   state_machine_attr: ClassVar[str]      = 'sm'
    #   state_machine_name: ClassVar[str]      = 'core.statemachines.ArchiveResultMachine'
    #   retry_at_field_name: ClassVar[str]     = 'retry_at'
    #   state_field_name: ClassVar[str]        = 'status'
    #   active_state: ClassVar[str]            = StatusChoices.STARTED
    
    # if ModelWithHealthStats model:
    #   num_uses_failed = models.PositiveIntegerField(default=0)
    #   num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    _prefetched_objects_cache: Dict[str, Any]

    class Meta(TypedModelMeta):
        abstract = True

    @classproperty
    def TYPE(cls) -> str:
        """Get the full Python dotted-import path for this model, e.g. 'core.models.Snapshot'"""
        return f'{cls.__module__}.{cls.__name__}'
    
    @admin.display(description='Summary')
    def __str__(self) -> str:
        return f'[{self.abid or (self.abid_prefix + "NEW")}] {self.__class__.__name__} {eval(self.abid_uri_src)}'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Overriden __init__ method ensures we have a stable creation timestamp that fields can use within initialization code pre-saving to DB."""
        super().__init__(*args, **kwargs)   # type: ignore
        
        # pre-compute a stable timestamp of the obj init time (with abid.ts precision limit applied) for use when object is first created,
        # some other fields depend on a timestamp at creation time, and it's nice to have one common timestamp they can all share.
        # Used as an alternative to auto_now_add=True + auto_now=True which can produce two different times & requires saving to DB to get the TS.
        # (ordinarily fields cant depend on other fields until the obj is saved to db and recalled)
        self._init_timestamp = ts_from_abid(abid_part_from_ts(timezone.now()))

    def check(self):
        super().check()
        assert 'id' in self._meta.get_fields(), 'All ABIDModel subclasses must define an id field'
        assert 'abid' in self._meta.get_fields(), 'All ABIDModel subclasses must define an abid field'
        assert 'created_at' in self._meta.get_fields(), 'All ABIDModel subclasses must define a created_at field'
        assert 'modified_at' in self._meta.get_fields(), 'All ABIDModel subclasses must define a modified_at field'
        assert 'created_by' in self._meta.get_fields(), 'All ABIDModel subclasses must define a created_by field'

    def clean(self, abid_drift_allowed: bool | None=None) -> None:
        if self._state.adding:
            # only runs once when a new object is first saved to the DB
            # sets self.id, self.pk, self.created_by, self.created_at, self.modified_at
            self._previous_abid = None
            self.abid = str(self.issue_new_abid())

        else:
            # otherwise if updating, make sure none of the field changes would invalidate existing ABID
            abid_diffs = self.ABID_FRESH_DIFFS
            if abid_diffs:
                # change has invalidated the existing ABID, raise a nice ValidationError pointing out which fields caused the issue

                keys_changed = ', '.join(diff['abid_src'] for diff in abid_diffs.values())
                full_summary = (
                    f"This {self.__class__.__name__}(abid={str(self.ABID)}) was assigned a fixed, unique ID (ABID) based on its contents when it was created. " +
                    f"\nYou must reduce your changes to not affect these fields [{keys_changed}], or create a new {self.__class__.__name__} object instead."
                )

                change_error = ValidationError({
                    **{
                        # url: ValidationError('Cannot update self.url= https://example.com/old -> https://example.com/new ...')
                        diff['abid_src'].replace('self.', '')
                            if (diff['old_val'] != diff['new_val']) and hasattr(self, diff['abid_src'].replace('self.', ''))
                            else NON_FIELD_ERRORS
                        : ValidationError(
                            'Cannot update %(abid_src)s= "%(old_val)s" -> "%(new_val)s" (would alter %(model)s.ABID.%(key)s=%(old_hash)s to %(new_hash)s)',
                            code='ABIDConflict',
                            params=diff,
                        )
                        for diff in abid_diffs.values()
                    },
                    NON_FIELD_ERRORS: ValidationError(full_summary),
                })

                allowed_to_invalidate_abid = self.abid_drift_allowed if (abid_drift_allowed is None) else abid_drift_allowed
                if allowed_to_invalidate_abid:
                    # print(f'\n#### WARNING: Change allowed despite it invalidating the ABID of an existing record ({self.__class__.__name__}.abid_drift_allowed={self.abid_drift_allowed})!', self.abid)
                    # print(change_error)
                    # print('--------------------------------------------------------------------------------------------------')
                    pass
                else:
                    print(f'\n#### ERROR:   Change blocked because it would invalidate ABID of an existing record ({self.__class__.__name__}.abid_drift_allowed={self.abid_drift_allowed})', self.abid)
                    print(change_error)
                    print('--------------------------------------------------------------------------------------------------')
                    raise change_error

    def save(self, *args: Any, abid_drift_allowed: bool | None=None, **kwargs: Any) -> None:
        """Overriden save method ensures new ABID is generated while a new object is first saving."""

        self.clean(abid_drift_allowed=abid_drift_allowed)

        return super().save(*args, **kwargs)
    
    @classmethod
    def id_from_abid(cls, abid: str) -> str:
        return str(cls.objects.only('pk').get(abid=cls.abid_prefix + str(abid).split('_', 1)[-1]).pk)


    @property
    def ABID_SOURCES(self) -> Dict[str, str]:
        """"Get the dict of fresh ABID component values based on the live object's properties."""
        assert self.abid_prefix
        return {
            'prefix': 'self.abid_prefix',             # defined as static class vars at build time
            'ts': self.abid_ts_src,
            'uri': self.abid_uri_src,
            'subtype': self.abid_subtype_src,
            'rand': self.abid_rand_src,
            'salt': 'self.abid_salt',                 # defined as static class vars at build time
        }

    @property
    def ABID_FRESH_VALUES(self) -> Dict[str, Any]:
        """"Get the dict of fresh ABID component values based on the live object's properties."""
        abid_sources = self.ABID_SOURCES
        assert all(src != 'None' for src in abid_sources.values())
        return {
            'prefix': eval(abid_sources['prefix']),
            'ts': eval(abid_sources['ts']),
            'uri': eval(abid_sources['uri']),
            'subtype': eval(abid_sources['subtype']),
            'rand': eval(abid_sources['rand']),
            'salt': eval(abid_sources['salt']),
        }
    
    @property
    def ABID_FRESH_HASHES(self) -> Dict[str, str]:
        """"Get the dict of fresh ABID component hashes based on the live object's properties."""
        abid_values = self.ABID_FRESH_VALUES
        assert all(val for val in abid_values.values())
        return abid_hashes_from_values(
            prefix=abid_values['prefix'],
            ts=abid_values['ts'],
            uri=abid_values['uri'],
            subtype=abid_values['subtype'],
            rand=abid_values['rand'],
            salt=abid_values['salt'],
        )
    
    @property
    def ABID_FRESH_DIFFS(self) -> Dict[str, Dict[str, Any]]:
        """Get the dict of discrepancies between the existing saved ABID and a new fresh ABID computed based on the live object."""
        existing_abid = self.ABID
        existing_values = {} if self._state.adding else self.__class__.objects.get(pk=self.pk).ABID_FRESH_VALUES
        abid_sources = self.ABID_SOURCES
        fresh_values = self.ABID_FRESH_VALUES
        fresh_hashes = self.ABID_FRESH_HASHES
        return {
            key: {
                'key': key,
                'model': self.__class__.__name__,
                'pk': self.pk,
                'abid_src': abid_sources[key],
                'old_val': existing_values.get(key, None),
                'old_hash': getattr(existing_abid, key),
                'new_val': fresh_values[key],
                'new_hash': new_hash,
                'summary': f'{abid_sources[key]}= "{existing_values.get(key, None)}" -> "{fresh_values[key]}" (would alter {self.__class__.__name__.lower()}.ABID.{key}={getattr(existing_abid, key)} to {new_hash})',
            }
            for key, new_hash in fresh_hashes.items()
            if getattr(existing_abid, key) != new_hash
        }

    def issue_new_abid(self, overwrite=False) -> ABID:
        """
        Issue a new ABID based on the current object's properties, can only be called once on new objects (before they are saved to DB).
        """
        if not overwrite:
            assert self._state.adding, 'Can only issue new ABID when model._state.adding is True'
        assert eval(self.abid_uri_src), f'Can only issue new ABID if self.abid_uri_src is defined ({self.abid_uri_src}={eval(self.abid_uri_src)})'

        # Setup Field defaults to be ready for ABID generation
        self.abid = None
        self.id = self.id or uuid4()
        self.pk = self.id
        self.created_at = self.created_at or self._init_timestamp  # cut off precision to match precision of TS component
        self.modified_at = self.modified_at or self.created_at
        self.created_by_id = (hasattr(self, 'created_by_id') and self.created_by_id) or get_or_create_system_user_pk()
        
        # Compute fresh ABID values & hashes based on object's live properties
        abid_fresh_values = self.ABID_FRESH_VALUES
        assert all(abid_fresh_values.values()), f'All ABID_FRESH_VALUES must be set {abid_fresh_values}'
        abid_fresh_hashes = self.ABID_FRESH_HASHES
        assert all(abid_fresh_hashes.values()), f'All ABID_FRESH_HASHES must be able to be generated {abid_fresh_hashes}'
        
        new_abid = ABID(**abid_fresh_hashes)
        
        assert new_abid.ulid and new_abid.uuid and new_abid.typeid, f'Failed to calculate {abid_fresh_values["prefix"]}_ABID for {self.__class__.__name__}'

        return new_abid

    @property
    def ABID(self) -> ABID:
        """
        Get the object's existing ABID (from self.abid if it's already saved to DB, otherwise generated fresh)
        e.g. -> ABID(ts='01HX9FPYTR', uri='E4A5CCD9', subtype='00', rand='ZYEBQE')
        """

        if self.abid:
            return ABID.parse(cast(str, self.abid))
        
        return self.issue_new_abid()

    # These are all example helpers to make it easy to access alternate formats of the ABID.*, only add them if you actually need them
    # @property
    # def UUID(self) -> UUID:
    #     """
    #     Get a uuid.UUID (v4) representation of the object's ABID.
    #     """
    #     return self.ABID.uuid
    
    # @property
    # def uuid(self) -> str:
    #     """
    #     Get a str uuid.UUID (v4) representation of the object's ABID.
    #     """
    #     return str(self.ABID.uuid)
    
    # @property
    # def ULID(self) -> ULID:
    #     """
    #     Get a ulid.ULID representation of the object's ABID.
    #     """
    #     return self.ABID.ulid

    # @property
    # def TypeID(self) -> TypeID:
    #     """
    #     Get a typeid.TypeID (stripe-style) representation of the object's ABID.
    #     """
    #     return self.ABID.typeid
    
    @property
    def api_url(self) -> str:
        """
        Compute the REST API URL to access this object.
        e.g. /api/v1/core/snapshot/snp_01BJQMF54D093DXEAWZ6JYRP
        """
        return reverse_lazy('api-1:get_any', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        """
        Compute the REST API Documentation URL to learn about accessing this object.
        e.g. /api/v1/docs#/Core%20Models/api_v1_core_get_snapshots
        """
        return f'/api/v1/docs#/{self._meta.app_label.title()}%20Models/api_v1_{self._meta.app_label}_get_{self._meta.db_table}'

    @property
    def admin_change_url(self) -> str:
        return f"/admin/{self._meta.app_label}/{self._meta.model_name}/{self.pk}/change/"

    def get_absolute_url(self):
        return self.api_docs_url
    
    def update_for_workers(self, **update_kwargs) -> bool:
        """Immediately update the **kwargs on the object in DB, and reset the retry_at to now()"""
        updated = bool(self._meta.model.objects.filter(pk=self.pk).update(**{'retry_at': timezone.now(), **update_kwargs}))
        self.refresh_from_db()
        return updated


class ModelWithHealthStats(models.Model):
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    class Meta:
        abstract = True
    
    def record_health_failure(self) -> None:
        self.num_uses_failed += 1
        self.save()

    def record_health_success(self) -> None:
        self.num_uses_succeeded += 1
        self.save()
        
    def reset_health(self) -> None:
        # move all the failures to successes when resetting so we dont lose track of the total count
        self.num_uses_succeeded = self.num_uses_failed + self.num_uses_succeeded
        self.num_uses_failed = 0
        self.save()
        
    @property
    def health(self) -> int:
        total_uses = max((self.num_uses_failed + self.num_uses_succeeded, 1))
        success_pct = (self.num_uses_succeeded / total_uses) * 100
        return round(success_pct)


class ModelWithConfig(ABIDModel):
    """
    Base Model that adds a config property to any ABIDModel.
    This config is retrieved by abx.pm.hook.get_scope_config(...) later whenever this model is used.
    """
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    
    class Meta:
        abstract = True

    # @property
    # def unique_config(self) -> dict[str, Any]:
    #     """Get the unique config that this model is adding to the default config"""
    #     without_us = archivebox.pm.hook.get_scope_config()
    #     with_us = archivebox.pm.hook.get_scope_config(extra_config=self.config)
    #     return {
    #         key: value
    #         for key, value in with_us.items()
    #         if key not in without_us
    #         or without_us[key] != value
    #     }


class ModelWithOutputDir(ABIDModel):
    """
    Base Model that adds an output_dir property to any ABIDModel.
    
    It creates the directory on .save(with_indexes=True), automatically migrating any old data if needed.
    It then writes the indexes to the output_dir on .save(write_indexes=True).
    It also makes sure the output_dir is in sync with the model.
    """
    class Meta:
        abstract = True
        
    # output_dir = models.FilePathField(path=CONSTANTS.DATA_DIR, max_length=200, blank=True, null=True)
    # output_files = models.TextField(default='')
    #      format:   <sha256_hash>,<blake3_hash>,<size>,<content-type>,<path>
    #                ...,...,123456,text/plain,index.merkle
    #                ...,...,123456,text/html,index.html
    #                ...,...,123456,application/json,index.json
    #                ...,...,123456,text/html,singlefile/index.html

    def save(self, *args, write_indexes=False, **kwargs) -> None:
        super().save(*args, **kwargs)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.save_json_index()    # always write index.json to data/snapshots/snp_2342353k2jn3j32l4324/index.json
        if write_indexes:
            self.write_indexes()  # write the index.html, merkle hashes, symlinks, send indexable texts to search backend, etc.

    @property
    def output_dir_parent(self) -> str:
        """Get the model type parent directory name that holds this object's data e.g. 'archiveresults'"""
        parent_dir = getattr(self, 'output_dir_parent', f'{self._meta.model_name}s')
        assert len(parent_dir) > 2, f'output_dir_parent must be a non-empty string, got: "{parent_dir}"'
        return parent_dir
    
    @property
    def output_dir_name(self) -> str:
        """Get the subdirectory name for the filesystem directory that holds this object's data e.g. 'snp_2342353k2jn3j32l4324'"""
        assert self.ABID
        return str(self.ABID)    # e.g. snp_2342353k2jn3j32l4324
    
    @property
    def output_dir_str(self) -> str:
        """Get relateive the filesystem directory Path that holds that data for this object e.g. 'snapshots/snp_2342353k2jn3j32l4324'"""
        return f'{self.output_dir_parent}/{self.output_dir_name}'  # e.g. snapshots/snp_2342353k2jn3j32l4324
        
    @property
    def OUTPUT_DIR(self) -> Path:
        """Get absolute filesystem directory Path that holds that data for this object e.g. Path('/data/snapshots/snp_2342353k2jn3j32l4324')"""
        from archivebox import DATA_DIR
        return DATA_DIR / self.output_dir_str        # e.g. /data/snapshots/snp_2342353k2jn3j32l4324
        
    def write_indexes(self):
        """Write the Snapshot json, html, and merkle indexes to its output dir"""
        print(f'{type(self).__name__}[{self.ABID}].write_indexes()')
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.migrate_output_dir()
        self.save_merkle_index()
        self.save_html_index()
        self.save_symlinks_index()
        
    def migrate_output_dir(self):
        """Move the output files to the new folder structure if needed"""
        print(f'{type(self).__name__}[{self.ABID}].migrate_output_dir()')
        self.migrate_from_0_7_2()
        self.migrate_from_0_8_6()
        # ... future migrations here
    
    def migrate_from_0_7_2(self) -> None:
        """Migrate output_dir generated by ArchiveBox <= 0.7.2 to current version"""
        print(f'{type(self).__name__}[{self.ABID}].migrate_from_0_7_2()')
        # move /data/archive/<timestamp> -> /data/archive/snapshots/<abid>
        # update self.output_path = /data/archive/snapshots/<abid>
        pass
    
    def migrate_from_0_8_6(self) -> None:
        """Migrate output_dir generated by ArchiveBox <= 0.8.6 to current version"""
        # ... future migration code here ...
        print(f'{type(self).__name__}[{self.ABID}].migrate_from_0_8_6()')
        pass

    def save_merkle_index(self, **kwargs) -> None:
        """Write the ./.index.merkle file to the output dir"""
        # write self.generate_merkle_tree() to self.output_dir / '.index.merkle'
        print(f'{type(self).__name__}[{self.ABID}].save_merkle_index()')
        pass
    
    def save_html_index(self, **kwargs) -> None:
        # write self.as_html() to self.output_dir / 'index.html'
        print(f'{type(self).__name__}[{self.ABID}].save_html_index()')
        pass
    
    def save_json_index(self, **kwargs) -> None:
        print(f'{type(self).__name__}[{self.ABID}].save_json_index()')
        # write self.as_json() to self.output_dir / 'index.json'
        (self.OUTPUT_DIR / 'index.json').write_text(to_json(self.as_json()))
        pass
    
    def save_symlinks_index(self) -> None:
        print(f'{type(self).__name__}[{self.ABID}].save_symlinks_index()')
        # ln -s ../../../../self.output_dir data/index/snapshots_by_date/2024-01-01/example.com/<abid>
        # ln -s ../../../../self.output_dir data/index/snapshots_by_domain/example.com/2024-01-01/<abid>
        # ln -s self.output_dir data/archive/1453452234234.21445
        pass

    def as_json(self) -> dict:
        """Get the object's properties as a dict"""
        # dump the object's properties to a json-ready dict
        return {
            'TYPE': self.TYPE,
            'id': self.id,
            'abid': str(self.ABID),
            'str': str(self),
            'modified_at': self.modified_at,
            'created_at': self.created_at,
            'created_by_id': self.created_by_id,
            'status': getattr(self, 'status', None),
            'retry_at': getattr(self, 'retry_at', None),
            'notes': getattr(self, 'notes', None),
        }
    
    def as_html(self) -> str:
        """Get the object's properties as a html string"""
        # render snapshot_detail.html template with self as context and return html string
        return ''


####################################################

# Django helpers
def find_all_abid_prefixes() -> Dict[str, type[models.Model]]:
    """
    Return the mapping of all ABID prefixes to their models.
    e.g. {'tag_': core.models.Tag, 'snp_': core.models.Snapshot, ...}
    """
    import django.apps
    prefix_map = {}

    for model in django.apps.apps.get_models():
        abid_prefix = getattr(model, 'abid_prefix', None)
        if abid_prefix:
            prefix_map[abid_prefix] = model
    return prefix_map

def find_prefix_for_abid(abid: ABID) -> str:
    """
    Find the correct prefix for a given ABID that may have be missing a prefix (slow).
    e.g. ABID('obj_01BJQMF54D093DXEAWZ6JYRPAQ') -> 'snp_'
    """
    # if existing abid prefix is correct, lookup is easy
    model = find_model_from_abid(abid)
    if model:
        assert issubclass(model, ABIDModel)
        return model.abid_prefix

    # prefix might be obj_ or missing, fuzzy-search to find any object that matches
    return find_obj_from_abid_rand(abid)[0].abid_prefix

def find_model_from_abid_prefix(prefix: str) -> type[ABIDModel] | None:
    """
    Return the Django Model that corresponds to a given ABID prefix.
    e.g. 'tag_' -> core.models.Tag
    """
    prefix = abid_part_from_prefix(prefix)   # snp_... -> snp_

    import django.apps

    for model in django.apps.apps.get_models():
        if not issubclass(model, ABIDModel): continue   # skip non-ABID-enabled models
        if not hasattr(model, 'objects'): continue      # skip abstract models

        if (model.abid_prefix == prefix):
            return model

    return None

def find_model_from_abid(abid: ABID) -> type[models.Model] | None:
    """
    Shortcut for find_model_from_abid_prefix(abid.prefix)
    """
    return find_model_from_abid_prefix(abid.prefix)

def find_obj_from_abid_rand(rand: Union[ABID, str], model=None) -> List[ABIDModel]:
    """
    Find an object corresponding to an ABID by exhaustively searching using its random suffix (slow).
    e.g. 'obj_....................JYRPAQ' -> Snapshot('snp_01BJQMF54D093DXEAWZ6JYRPAQ')
    Honestly should only be used for debugging, no reason to expose this ability to users.
    """

    # convert str to ABID if necessary
    if isinstance(rand, ABID):
        abid: ABID = rand
    else:
        rand = str(rand)
        if len(rand) < ABID_SUFFIX_LEN:
            padding_needed = ABID_SUFFIX_LEN - len(rand)
            rand = ('0'*padding_needed) + rand
        abid = ABID.parse(rand)

    import django.apps

    partial_matches: List[ABIDModel] = []

    models_to_try = cast(Set[type[models.Model]], set(filter(bool, (
        model,
        find_model_from_abid(abid),
        *django.apps.apps.get_models(),
    ))))
    # print(abid, abid.rand, abid.uuid, models_to_try)

    for model in models_to_try:
        if not issubclass(model, ABIDModel): continue   # skip Models that arent ABID-enabled
        if not hasattr(model, 'objects'): continue      # skip abstract Models
        assert hasattr(model, 'objects')                # force-fix for type hint nit about missing manager https://github.com/typeddjango/django-stubs/issues/1684

        # continue on to try fuzzy searching by randomness portion derived from uuid field
        try:
            qs = []
            if hasattr(model, 'abid'):
                qs = model.objects.filter(abid__endswith=abid.rand)
            elif hasattr(model, 'uuid'):
                qs = model.objects.filter(uuid__endswith=str(abid.uuid)[-ABID_RAND_LEN:])
            elif hasattr(model, 'id'):
                # NOTE: this only works on SQLite where every column is a string
                # other DB backends like postgres dont let you do __endswith if this is a BigAutoInteger field
                
                # try to search for uuid=...-2354352
                # try to search for id=...2354352
                # try to search for id=2354352
                qs = model.objects.filter(
                    models.Q(id__endswith=str(abid.uuid)[-ABID_RAND_LEN:])
                    | models.Q(id__endswith=abid.rand)
                    | models.Q(id__startswith=str(int(abid.rand)) if abid.rand.isdigit() else abid.rand)
                )

            for obj in qs:
                if abid in (str(obj.ABID), str(obj.id), str(obj.pk), str(obj.abid)):
                    # found exact match, no need to keep iterating
                    return [obj]
                partial_matches.append(obj)
        except OperationalError as err:
            print(f'[!] WARNING: Got error while trying to iterate through QuerySet for {model}:', err, '\n')

    return partial_matches

def find_obj_from_abid(abid: ABID, model=None, fuzzy=False) -> Any:
    """
    Find an object with a given ABID by filtering possible models for a matching abid/uuid/id (fast).
    e.g. 'snp_01BJQMF54D093DXEAWZ6JYRPAQ' -> Snapshot('snp_01BJQMF54D093DXEAWZ6JYRPAQ')
    """

    model = model or find_model_from_abid(abid)
    assert model, f'Could not find model that could match this ABID type: {abid}'

    try:
        if hasattr(model, 'abid'):
            return model.objects.get(abid__endswith=abid.suffix)
        if hasattr(model, 'uuid'):
            return model.objects.get(uuid=abid.uuid)
        return model.objects.get(id=abid.uuid)
    except model.DoesNotExist:
        # if the model has an abid field then it shouldve matched, pointless to fuzzy search in that case
        if hasattr(model, 'abid') or (not fuzzy):
            raise

    # continue on to try fuzzy searching by randomness portion derived from uuid field
    match_by_rand = find_obj_from_abid_rand(abid, model=model)
    if match_by_rand:
        if match_by_rand[0].abid_prefix != abid.prefix:
            print(f'[!] WARNING: fetched object {match_by_rand} even though prefix {abid.prefix} doesnt match!', abid, '\n')
        return match_by_rand

    raise model.DoesNotExist

