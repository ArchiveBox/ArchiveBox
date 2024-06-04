"""
This file provides the Django ABIDField and ABIDModel base model to inherit from.

It implements the ArchiveBox ID (ABID) interfaces including abid_values, get_abid, .abid, .uuid, .id.
"""

from typing import Any, Dict, Union, List, Set, NamedTuple, cast

from ulid import ULID
from uuid import uuid4, UUID
from typeid import TypeID            # type: ignore[import-untyped]
from datetime import datetime
from functools import partial
from charidfield import CharIDField  # type: ignore[import-untyped]

from django.conf import settings
from django.db import models
from django.db.utils import OperationalError
from django.contrib.auth import get_user_model

from django_stubs_ext.db.models import TypedModelMeta

from .abid import (
    ABID,
    ABID_LEN,
    ABID_RAND_LEN,
    ABID_SUFFIX_LEN,
    DEFAULT_ABID_PREFIX,
    abid_part_from_prefix,
    abid_from_values
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
    user, created = User.objects.get_or_create(username=username, is_staff=True, is_superuser=True, defaults={'email': '', 'password': ''})
    return user.pk


class ABIDModel(models.Model):
    """
    Abstract Base Model for other models to depend on. Provides ArchiveBox ID (ABID) interface.
    """
    abid_prefix: str = DEFAULT_ABID_PREFIX  # e.g. 'tag_'
    abid_ts_src = 'None'                    # e.g. 'self.created'
    abid_uri_src = 'None'                   # e.g. 'self.uri'
    abid_subtype_src = 'None'               # e.g. 'self.extractor'
    abid_rand_src = 'None'                  # e.g. 'self.uuid' or 'self.id'

    id = models.UUIDField(primary_key=True, default=uuid4, editable=True)
    uuid = models.UUIDField(blank=True, null=True, editable=True, unique=True)
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta(TypedModelMeta):
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if hasattr(self, 'abid'):
            # self.abid = ABID.parse(self.abid) if self.abid else self.get_abid()
            self.abid = self.get_abid()
        else:
            print(f'[!] WARNING: {self.__class__.__name__}.abid is not a DB field so ABID will not be persisted!')
            self.abid = self.get_abid()
        
        super().save(*args, **kwargs)

    @property
    def abid_values(self) -> Dict[str, Any]:
        return {
            'prefix': self.abid_prefix,
            'ts': eval(self.abid_ts_src),
            'uri': eval(self.abid_uri_src),
            'subtype': eval(self.abid_subtype_src),
            'rand': eval(self.abid_rand_src),
        }

    def get_abid(self) -> ABID:
        """
        Return a freshly derived ABID (assembled from attrs defined in ABIDModel.abid_*_src).
        """
        prefix, ts, uri, subtype, rand = self.abid_values.values()

        if (not prefix) or prefix == DEFAULT_ABID_PREFIX:
            suggested_abid = self.__class__.__name__[:3].lower()
            raise Exception(f'{self.__class__.__name__}.abid_prefix must be defined to calculate ABIDs (suggested: {suggested_abid})')

        if not ts:
            ts = datetime.utcfromtimestamp(0)
            print(f'[!] WARNING: Generating ABID with ts=0000000000 placeholder because {self.__class__.__name__}.abid_ts_src={self.abid_ts_src} is unset!', ts.isoformat())

        if not uri:
            uri = str(self)
            print(f'[!] WARNING: Generating ABID with uri=str(self) placeholder because {self.__class__.__name__}.abid_uri_src={self.abid_uri_src} is unset!', uri)

        if not subtype:
            subtype = self.__class__.__name__
            print(f'[!] WARNING: Generating ABID with subtype={subtype} placeholder because {self.__class__.__name__}.abid_subtype_src={self.abid_subtype_src} is unset!', subtype)

        if not rand:
            rand = getattr(self, 'uuid', None) or getattr(self, 'id', None) or getattr(self, 'pk')
            print(f'[!] WARNING: Generating ABID with rand=self.id placeholder because {self.__class__.__name__}.abid_rand_src={self.abid_rand_src} is unset!', rand)

        abid = abid_from_values(
            prefix=prefix,
            ts=ts,
            uri=uri,
            subtype=subtype,
            rand=rand,
        )
        assert abid.ulid and abid.uuid and abid.typeid, f'Failed to calculate {prefix}_ABID for {self.__class__.__name__}'
        return abid

    @property
    def ABID(self) -> ABID:
        """
        ULIDParts(timestamp='01HX9FPYTR', url='E4A5CCD9', subtype='00', randomness='ZYEBQE')
        """
        return ABID.parse(self.abid) if getattr(self, 'abid', None) else self.get_abid()

    @property
    def ULID(self) -> ULID:
        """
        Get a ulid.ULID representation of the object's ABID.
        """
        return self.ABID.ulid

    @property
    def UUID(self) -> UUID:
        """
        Get a uuid.UUID (v4) representation of the object's ABID.
        """
        return self.ABID.uuid

    @property
    def TypeID(self) -> TypeID:
        """
        Get a typeid.TypeID (stripe-style) representation of the object's ABID.
        """
        return self.ABID.typeid



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
                if obj.get_abid() == abid:
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

