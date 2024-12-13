__package__ = 'archivebox.tags'

import uuid
from typing import Type, ClassVar, Iterable, Any

from benedict import benedict

from django.db import models, transaction
from django.db.models import QuerySet, F
from django.db.models.functions import Substr, StrIndex, Concat
from django.conf import settings

from django.utils.text import slugify
from django.utils.functional import classproperty              # type: ignore
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation


from base_models.models import ABIDModel, ABIDField, AutoDateTimeField, get_or_create_system_user_pk

FORBIDDEN_TAG_CHARS = ('=', '\n', '\t', '\r', ',', '\'', '"', '\\')


class KVTagManager(models.Manager):
    pass

class KVTagQuerySet(models.QuerySet):
    """
    Enhanced QuerySet for KVTag objects.
    
    To list all unique tag names:
        KVTag.objects.filter(obj__created_by_id=123).names() -> {'tag1', 'tag2', 'tag3'}
    
    To list all the Snapshot objects with a given tag:
        KVTag.objects.filter(name='tag1').objects(Snapshot) -> QuerySet[Snapshot]: [snapshot1, snapshot2, snapshot3]

    To rename a tag "abcd" to "xyz":
        KVTag.objects.filter(name='abcd').rename(name='xyz') -> QuerySet[KVTag]: [xyz, xyz, xyz]
    """
    
    def kvtags(self) -> 'KVTagQuerySet':
        return self.filter(value__isnull=False)
    
    def non_kvtags(self) -> 'KVTagQuerySet':
        return self.filter(value__isnull=True)
    
    def rename(self, name: str) -> 'KVTagQuerySet':
        self.update(name=name)
        return self._clone()

    def names(self) -> set[str]:
        """get the unique set of names of tags in this queryset"""
        return set(self.non_kvtags().values('name').distinct().values_list('name', flat=True))
    
    def keys(self) -> set[str]:
        """get the unique set of keys of tags in this queryset"""
        return set(self.kvtags().values('name').distinct().values_list('name', flat=True))

    def values(self) -> set[str]:
        """get the unique set of values of tags in this queryset"""
        return set(self.kvtags().values_list('value').distinct().values_list('value', flat=True))
    
    def tag_dict(self) -> dict[str, str]:
        """
        Returns a dictionary of dictionaries, where the outer key is the obj_id and the inner key is the tag name.
        {
            'abcd-2345-2343-234234': {
                'uuid': 'abcd-2345-2343-234234',
                'sha256': 'abc123k3j423kj423kl4j23',
                'path': '/data/sources/2024-01-02_11-57-51__cli_add.txt',
                'some-flat-tag': None,
                'some-other-tag': None,
            },
            'efgh-2345-2343-234234': {
                ...
            },
        }
        """
        tag_dict = {}
        for tag in self:
            tag_dict[tag.obj_id] = tag_dict.get(tag.obj_id, {})
            tag_dict[tag.obj_id][tag.key] = tag_dict[tag.obj_id].get(tag.key, tag.value)

        return benedict(tag_dict)

    def model_classes(self) -> list[Type[models.Model]]:
        """get the unique set of Model classes of objects in this queryset"""
        obj_types = set(self.values('obj_type').distinct().values_list('obj_type', flat=True))
        return [obj_type.model_class() for obj_type in obj_types]
    
    def model_class(self) -> Type[models.Model]:
        """get the single Model class of objects in this queryset (or raise an error if there are multiple types)"""
        model_classes = self.model_classes()
        assert len(model_classes) == 1, f'KVTagQuerySet.model_class() can only be called when the queried objects are all a single type (found multiple types: {model_classes})'
        return model_classes[0]
    
    def objects(self, model_class: Type[models.Model] | ContentType | None = None) -> QuerySet:
        """Get the queryset of objects that have the tags we've selected (pass a Model or ContentType to filter by obj_type)"""
        Model: Type[models.Model]
        
        if isinstance(model_class, ContentType):
            Model = model_class.model_class()
        elif model_class is None:
            # if no explicit obj_type is provided, try to infer it from the queryset (raises error if queryset is a mixture of multiple types)
            Model = self.model_class()
        else:
            Model = model_class

        # at this point model_class should be a model class
        assert issubclass(Model, models.Model)
        
        # the the queryset of objects that have the tags we've selected
        obj_ids = self.values_list('obj_id', flat=True)
        return Model.objects.filter(id__in=obj_ids)
    

    # In the future, consider:
    # def delete(self) -> None:
    #    self.update(deleted_at=timezone.now())



class KVTag(ModelWithReadOnlyFields):
    """
    Very flexible K:V tagging system that allows you to tag any model with any tag.
    e.g. to tag a Snapshot with 3 tags:
        KVTag.objects.create(obj=snapshot1, name='tag1-simple some text')
        snapshot1.tags.create(name='tag1-simple some text')  <- this duplicate would be blocked by an IntegrityError (obj_id + name must be unique)
        
        snapshot1.tags.create(name='ABID', value='snp_abc123k3j423kj423kl4j23')
        snapshot1.tags.create(name='SHA256', value='1234234abc123k3j423kj423kl4j23')
        snapshot1.tags.create(name='SAVE_WGET', value='False')
        snapshot1.tags.create(name='URI', value='file:///data/sources/2024-01-02_11-57-51__cli_add.txt')
    """
    
    ####################### All fields are immutable! ###########################
    #                  enforced by ModelWithReadOnlyFields
    read_only_fields = ('id', 'created_at', 'name', 'value', 'obj_type', 'obj_id')
    #############################################################################
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)

    name = models.CharField(null=False, blank=False, max_length=255, db_index=True)
    value = models.TextField(null=True, blank=True, db_default=Substr('name', StrIndex('name', '=')))

    obj_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=False, blank=False, default=None, db_index=True)
    obj_id = models.UUIDField(null=False, blank=False, default=None, db_index=True)
    obj = GenericForeignKey('obj_type', 'obj_id')

    objects: KVTagManager = KVTagManager.from_queryset(KVTagQuerySet)()

    class Meta:
        db_table = 'core_KVTags'
        unique_together = [('obj_id', 'name')]
    
    def __str__(self) -> str:
        return self.keyval_str if self.name else '<new-KVTag>'
    
    def __repr__(self) -> str:
        return f'#{self.name}'

    @property
    def key(self) -> str:
        self.clean()
        return self.name
    
    @property
    def val(self) -> str | None:
        self.clean()
        return self.value
    
    @property
    def keyval_str(self) -> str:
        self.clean()
        return f'{self.key}={self.value}' if self.value else self.key
    
    @staticmethod
    def parse_keyval_str(keyval_str: str) -> tuple[str, str | None]:
        name, value = keyval_str.split('=', 1) if ('=' in keyval_str) else (keyval_str, '')
        return name.strip(), value.strip() or None
    
    def clean(self) -> None:
        # check that the object being tagged is not a KVTag object itself
        kvtag_obj_type = ContentType.objects.get_for_model(self.__class__)
        assert self.obj_type != kvtag_obj_type, f'A KVTag(obj_type={self.obj_type}).obj -> {self.obj} points to another KVTag object (you cannot tag a KVTag with another KVTag)'
        
        # check that the object being tagged inherits from ModelWithKVTags
        assert isinstance(self.obj, ModelWithKVTags), f"A KVTag(obj_type={self.obj_type}).obj -> {self.obj} points to an object that doesn't support tags (you can only tag models that inherit from ModelWithKVTags)"

        # parse key, value from name if it contains an = sign, otherwise key = name & val = None
        name, value = self.parse_keyval_str(self.name)
        
        # update values with cleaned values
        self.name = self.name or name
        self.value = self.value or value
        
        assert isinstance(self.name, str) and self.name.strip(), f'KVTag(name={self.name}).name must be a non-empty string'
        
        # check if tag is a simple key
        if self.value is None:
            # basic (lax) check for forbidden characters
            unallowed_chars = [char for char in self.name if char in FORBIDDEN_TAG_CHARS]
            assert not unallowed_chars, f'KVTag(name={self.name}).name contains symbols or whitespace that are not allowed: {unallowed_chars[0]}'
            
        # check if tag is a key=value pair
        else:
            # strict check that key is a valid identifier
            assert self.name.isidentifier(), f'KVTag(name={self.value}).name must be a valid identifier string (a-Z, 0-9, _)'
            
            # basic (lax) check for forbidden characters in value
            unallowed_chars = [char for char in self.name if char in FORBIDDEN_TAG_CHARS]
            assert isinstance(self.value, str) and self.value.strip() and not unallowed_chars, f'KVTag(value={self.value}).value must be a non-empty string (with no newlines, commas, = signs, quotes, or forward slashes)'

    def save(self, *args, **kwargs) -> None:
        self.clean()        
        super().save(*args, **kwargs)
    
    @property
    def slug(self) -> str:
        return slugify(self.name)
    
    @property
    def created_by_id(self) -> User:
        if self.obj and hasattr(self.obj, 'created_by_id'):
            return self.obj.created_by_id
        return get_or_create_system_user_pk()
    
    @property
    def created_by(self) -> User:
        return User.objects.get(pk=self.created_by_id)


class ModelWithKVTags(ModelWithReadOnlyFields):
    """
    A base class for models that have tags, adds 0 additional storage overhead to models with 0 tags.
    
    Snapshot.objects.get(id='...').tags.clear()
    Snapshot.objects.get(id='...').tags.create(name='tag1')
    Snapshot.objects.get(id='...').tags.create(name='tag2', value='some-value')
    Snapshot.objects.get(id='...').tags.create(name='tag3')
    Snapshot.objects.get(id='...').tags.filter(name='tag3').delete()
    snapshot.objects.get(id='...').tag_names -> ['tag1', 'tag2']
    snapshot.objects.get(id='...').tag_dict -> {'tag1': None, 'tag2': 'some-value'}
    snapshot.objects.get(id='...').tag_csv -> 'tag1,tag2'
    """
    
    read_only_fields = ('id',)
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, null=False, editable=False, unique=True, verbose_name='ID')
    
    tag_set = GenericRelation(
        KVTag,
        # related_query_name="snapshot",       set this in subclasses, allows queries like KVTag.objects.filter(snapshot__url='https://example.com')
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    kvtag_set = tag_set
    
    class Meta:
        abstract = True

    @classproperty
    def content_type(cls) -> ContentType:
        return ContentType.objects.get_for_model(cls)
    
    @property
    def tag_dict(self) -> dict[str, str]:
        """
        {
            '⭐️': None,
            'some-other-tag': None,
            'some tag/testing 234[po4]': None,
            'uuid': 'abcd-2345-2343-234234',
            'sha256': 'abc123k3j423kj423kl4j23',
            'file': '/data/sources/2024-01-02_11-57-51__cli_add.txt',
        }
        """
        return benedict({
            tag.key: tag.value
            for tag in self.tag_set.order_by('created_at')
        })
        
    def get_tag_value(self, tag_name: str) -> str | None:
        """get the value of a tag with the given name pointing to this object, or None if no matching tag exists"""
        tag = self.tag_set.filter(name=tag_name).order_by('created_at').last()
        return tag and tag.value
    
    def set_tag_value(self, tag_name: str, tag_value: str | None) -> KVTag:
        """create or update a Tag pointing to this objects with the given name, to the given value"""
        with transaction.atomic():
            tag, _created = KVTag.objects.update_or_create(obj=self, name=tag_name, defaults={'value': tag_value})
            tag.save()
        return tag
    
    @property
    def tag_names(self) -> list[str]:
        return [str(tag) for tag in self.tag_set.order_by('created_at')]
    
    @tag_names.setter
    def tag_names_setter(self, tag_names: list[str]) -> None:
        kvtags = []
        for tag_name in tag_names:
            key, value = KVTag.parse_keyval_str(tag_name)
            kvtags.append(self.set_tag_value(key, value))
        self.tag_set.set(kvtags)
    
    @property
    def tags_csv(self) -> str:
        return ','.join(self.tag_names)

    # Meh, not really needed:
    # @tags_csv.setter
    # def tags_csv_setter(self, tags_csv: str) -> None:
    #     with transaction.atomic():
    #         # delete all existing tags
    #         self.tag_set.delete()
    #
    #         # add a new tag for each comma-separated value in tags_str
    #         new_kvtags = []
    #         for tag_name in tags_csv.split(','):
    #             new_kvtags.append(KVTag(obj=self, name=tag_name))
    #
    #         KVTag.objects.bulk_create(new_kvtags)
    #         self.tag_set.set(new_kvtags)
