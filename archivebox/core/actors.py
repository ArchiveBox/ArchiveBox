__package__ = 'archivebox.core'

from typing import ClassVar

from rich import print

from django.db.models import QuerySet
from django.utils import timezone
from datetime import timedelta
from core.models import Snapshot

from actors.actor import ActorType


class SnapshotActor(ActorType[Snapshot]):
    
    QUERYSET: ClassVar[QuerySet] = Snapshot.objects.filter(status='queued')
    CLAIM_WHERE: ClassVar[str] = 'status = "queued"'  # the WHERE clause to filter the objects when atomically getting the next object from the queue
    CLAIM_SET: ClassVar[str] = 'status = "started"'   # the SET clause to claim the object when atomically getting the next object from the queue
    CLAIM_ORDER: ClassVar[str] = 'created_at DESC'    # the ORDER BY clause to sort the objects with when atomically getting the next object from the queue
    CLAIM_FROM_TOP: ClassVar[int] = 50                # the number of objects to consider when atomically getting the next object from the queue
    
    # model_type: Type[ModelType]
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 4               # min 2, max 8, up to 60% of available cpu cores
    MAX_TICK_TIME: ClassVar[int] = 60                          # maximum duration in seconds to process a single object
    
    def claim_sql_where(self) -> str:
        """override this to implement a custom WHERE clause for the atomic claim step e.g. "status = 'queued' AND locked_by = NULL" """
        return self.CLAIM_WHERE
    
    def claim_sql_set(self) -> str:
        """override this to implement a custom SET clause for the atomic claim step e.g. "status = 'started' AND locked_by = {self.pid}" """
        retry_at = timezone.now() + timedelta(seconds=self.MAX_TICK_TIME)
        # format as 2024-10-31 10:14:33.240903
        retry_at_str = retry_at.strftime('%Y-%m-%d %H:%M:%S.%f')
        return f'{self.CLAIM_SET}, retry_at = {retry_at_str}'
    
    def claim_sql_order(self) -> str:
        """override this to implement a custom ORDER BY clause for the atomic claim step e.g. "created_at DESC" """
        return self.CLAIM_ORDER
    
    def claim_from_top(self) -> int:
        """override this to implement a custom number of objects to consider when atomically claiming the next object from the top of the queue"""
        return self.CLAIM_FROM_TOP
        
    def tick(self, obj: Snapshot) -> None:
        """override this to process the object"""
        print(f'[blue]🏃‍♂️ {self}.tick()[/blue]', obj.abid or obj.id)
        # For example:
        # do_some_task(obj)
        # do_something_else(obj)
        # obj._model.objects.filter(pk=obj.pk, status='started').update(status='success')
        # raise NotImplementedError('tick() must be implemented by the Actor subclass')
    
    def on_shutdown(self, err: BaseException | None=None) -> None:
        print(f'[grey53]🏃‍♂️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_actor_shutdown(self)
        
    def on_tick_start(self, obj: Snapshot) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_start()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_start(self, obj_to_process)
        # self.timer = TimedProgress(self.MAX_TICK_TIME, prefix='      ')
        pass
    
    def on_tick_end(self, obj: Snapshot) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_end()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_end(self, obj_to_process)
        # self.timer.end()
        pass
    
    def on_tick_exception(self, obj: Snapshot, err: BaseException) -> None:
        print(f'[red]🏃‍♂️ {self}.on_tick_exception()[/red]', obj.abid or obj.id, err)
        # abx.pm.hook.on_actor_tick_exception(self, obj_to_process, err)
