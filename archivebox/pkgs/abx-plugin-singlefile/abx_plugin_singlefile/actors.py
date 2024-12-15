# __package__ = 'abx_plugin_singlefile'

# from typing import ClassVar
# from django.db.models import QuerySet
# from django.utils.functional import classproperty

# from workers.actor import ActorType

# from .models import SinglefileResult


# class SinglefileActor(ActorType[SinglefileResult]):
#     CLAIM_ORDER: ClassVar[str] = 'created_at DESC'
#     CLAIM_WHERE: ClassVar[str] = 'status = "queued" AND extractor = "favicon"'
#     CLAIM_SET: ClassVar[str] = 'status = "started"'
    
#     @classproperty
#     def QUERYSET(cls) -> QuerySet:
#         return SinglefileResult.objects.filter(status='queued')

#     def tick(self, obj: SinglefileResult):
#         print(f'[grey53]{self}.tick({obj.abid or obj.id}, status={obj.status}) remaining:[/grey53]', self.get_queue().count())
#         updated = SinglefileResult.objects.filter(id=obj.id, status='started').update(status='success') == 1
#         if not updated:
#             raise Exception(f'Failed to update {obj.abid or obj.id}, interrupted by another actor writing to the same object')
#         obj.refresh_from_db()
#         obj.save()
