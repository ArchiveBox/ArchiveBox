"""
This file provides the Django ABIDField and ABIDModel base model to inherit from.
"""


from typing import Any, Dict, Union, List, Set, cast

from uuid import uuid4
from functools import partial
from charidfield import CharIDField  # type: ignore[import-untyped]

from django.contrib import admin
from django.core.exceptions import ValidationError, NON_FIELD_ERRORS
from django.db import models
from django.utils import timezone
from django.db.utils import OperationalError
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy

from django_stubs_ext.db.models import TypedModelMeta

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


class ABIDModel(models.Model):
    """
    Abstract Base Model for other models to depend on. Provides ArchiveBox ID (ABID) interface.
    """
    abid_prefix: str = DEFAULT_ABID_PREFIX            # e.g. 'tag_'
    abid_ts_src = 'self.created_at'                  # e.g. 'self.created_at'
    abid_uri_src = 'None'                            # e.g. 'self.uri'                (MUST BE SET)
    abid_subtype_src = 'self.__class__.__name__'     # e.g. 'self.extractor'
    abid_rand_src = 'self.id'                        # e.g. 'self.uuid' or 'self.id'
    abid_salt: str = DEFAULT_ABID_URI_SALT           # combined with self.uri to anonymize hashes on a per-install basis (default is shared globally with all users, means everyone will hash ABC to -> 123 the same around the world, makes it easy to share ABIDs across installs and see if they are for the same URI. Change this if you dont want your hashes to be guessable / in the same hash space as all other users)
    abid_drift_allowed: bool = False                 # set to True to allow abid_field values to change after a fixed ABID has been issued (NOT RECOMMENDED: means values can drift out of sync from original ABID)

    # id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    # abid = ABIDField(prefix=abid_prefix)

    # created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)
    # created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    # modified_at = models.DateTimeField(auto_now=True)

    _prefetched_objects_cache: Dict[str, Any]

    class Meta(TypedModelMeta):
        abstract = True

    @admin.display(description='Summary')
    def __str__(self) -> str:
        return f'[{self.abid or (self.abid_prefix + "NEW")}] {self.__class__.__name__} {eval(self.abid_uri_src)}'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Overriden __init__ method ensures we have a stable creation timestamp that fields can use within initialization code pre-saving to DB."""
        super().__init__(*args, **kwargs)
        # pre-compute a stable timestamp of the obj init time (with abid.ts precision limit applied) for use when object is first created,
        # some other fields depend on a timestamp at creation time, and it's nice to have one common timestamp they can all share.
        # Used as an alternative to auto_now_add=True + auto_now=True which can produce two different times & requires saving to DB to get the TS.
        # (ordinarily fields cant depend on other fields until the obj is saved to db and recalled)
        self._init_timestamp = ts_from_abid(abid_part_from_ts(timezone.now()))

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
                    print(f'\n#### WARNING: Change allowed despite it invalidating the ABID of an existing record ({self.__class__.__name__}.abid_drift_allowed={self.abid_drift_allowed})!', self.abid)
                    print(change_error)
                    print('--------------------------------------------------------------------------------------------------')
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
            'salt': 'self.abid_salt',               # defined as static class vars at build time
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
    prefix = abid_part_from_prefix(prefix)

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

