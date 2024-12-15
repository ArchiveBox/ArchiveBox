# __package__ = 'archivebox.workers'

# import time


# from typing import ClassVar, Type, Iterable, TypedDict
# from django.db.models import QuerySet
# from django.db import transaction
# from django.utils import timezone
# from django.utils.functional import classproperty       # type: ignore

# from .models import Event, Process, EventDict


# class ActorType:
#     # static class attributes
#     name: ClassVar[str]
#     event_prefix: ClassVar[str]
#     poll_interval: ClassVar[int] = 1
    
#     @classproperty
#     def event_queue(cls) -> QuerySet[Event]:
#         return Event.objects.filter(type__startswith=cls.event_prefix)

#     @classmethod
#     def fork(cls, wait_for_first_event=False, exit_on_idle=True) -> Process:
#         cmd = ['archivebox', 'actor', cls.name]
#         if exit_on_idle:
#             cmd.append('--exit-on-idle')
#         if wait_for_first_event:
#             cmd.append('--wait-for-first-event')
#         return Process.create_and_fork(cmd=cmd, actor_type=cls.name)

#     @classproperty
#     def processes(cls) -> QuerySet[Process]:
#         return Process.objects.filter(actor_type=cls.name)

#     @classmethod
#     def run(cls, wait_for_first_event=False, exit_on_idle=True):

#         if wait_for_first_event:
#             event = cls.event_queue.get_next_unclaimed()
#             while not event:
#                 time.sleep(cls.poll_interval)
#                 event = cls.event_queue.get_next_unclaimed()

#         while True:
#             output_events = list(cls.process_next_event()) or list(cls.process_idle_tick())   # process next event, or tick if idle
#             yield from output_events
#             if not output_events:
#                 if exit_on_idle:
#                     break
#                 else:
#                     time.sleep(cls.poll_interval)

#     @classmethod
#     def process_next_event(cls) -> Iterable[EventDict]:
#         event = cls.event_queue.get_next_unclaimed()
#         output_events = []
        
#         if not event:
#             return []
        
#         cls.mark_event_claimed(event, duration=60)
#         try:
#             for output_event in cls.receive(event):
#                 output_events.append(output_event)
#                 yield output_event
#             cls.mark_event_succeeded(event, output_events=output_events)
#         except BaseException as e:
#             cls.mark_event_failed(event, output_events=output_events, error=e)

#     @classmethod
#     def process_idle_tick(cls) -> Iterable[EventDict]:
#         # reset the idle event to be claimed by the current process
#         event, _created = Event.objects.update_or_create(
#             name=f'{cls.event_prefix}IDLE',
#             emitted_by=Process.current(),
#             defaults={
#                 'deliver_at': timezone.now(),
#                 'claimed_proc': None,
#                 'claimed_at': None,
#                 'finished_at': None,
#                 'error': None,
#                 'parent': None,
#             },
#         )
        
#         # then process it like any other event
#         yield from cls.process_next_event()

#     @classmethod
#     def receive(cls, event: Event) -> Iterable[EventDict]:
#         handler_method = getattr(cls, f'on_{event.name}', None)
#         if handler_method:
#             yield from handler_method(event)
#         else:
#             raise Exception(f'No handler method for event: {event.name}')

#     @staticmethod
#     def on_IDLE() -> Iterable[EventDict]:
#         return []
    
#     @staticmethod
#     def mark_event_claimed(event: Event, duration: int=60):
#         proc = Process.current()
        
#         with transaction.atomic():
#             claimed = Event.objects.filter(id=event.id, claimed_proc=None, claimed_at=None).update(claimed_proc=proc, claimed_at=timezone.now())
#             if not claimed:
#                 event.refresh_from_db()
#                 raise Exception(f'Event already claimed by another process: {event.claimed_proc}')
            
#             process_updated = Process.objects.filter(id=proc.id, active_event=None).update(active_event=event)
#             if not process_updated:
#                 raise Exception(f'Unable to update process.active_event: {proc}.active_event = {event}')

#     @staticmethod
#     def mark_event_succeeded(event: Event, output_events: Iterable[EventDict]):
#         assert event.claimed_proc and (event.claimed_proc == Process.current())
#         with transaction.atomic():
#             updated = Event.objects.filter(id=event.id, claimed_proc=event.claimed_proc, claimed_at=event.claimed_at, finished_at=None).update(finished_at=timezone.now())
#             if not updated:
#                 event.refresh_from_db()
#                 raise Exception(f'Event {event} failed to mark as succeeded, it was modified by another process: {event.claimed_proc}')

#             process_updated = Process.objects.filter(id=event.claimed_proc.id, active_event=event).update(active_event=None)
#             if not process_updated:
#                 raise Exception(f'Unable to unset process.active_event: {event.claimed_proc}.active_event = {event}')

#         # dispatch any output events
#         for output_event in output_events:
#             Event.dispatch(event=output_event, parent=event)

#         # trigger any callback events
#         if event.on_success:
#             Event.dispatch(event=event.on_success, parent=event)

#     @staticmethod
#     def mark_event_failed(event: Event, output_events: Iterable[EventDict]=(), error: BaseException | None = None):
#         assert event.claimed_proc and (event.claimed_proc == Process.current())
#         with transaction.atomic():
#             updated = event.objects.filter(id=event.id, claimed_proc=event.claimed_proc, claimed_at=event.claimed_at, finished_at=None).update(finished_at=timezone.now(), error=str(error))
#             if not updated:
#                 event.refresh_from_db()
#                 raise Exception(f'Event {event} failed to mark as failed, it was modified by another process: {event.claimed_proc}')

#             process_updated = Process.objects.filter(id=event.claimed_proc.id, active_event=event).update(active_event=None)
#             if not process_updated:
#                 raise Exception(f'Unable to unset process.active_event: {event.claimed_proc}.active_event = {event}')

        
#         # add dedicated error event to the output events
#         output_events = [
#             *output_events,
#             {'name': f'{event.name}_ERROR', 'error': f'{type(error).__name__}: {error}'},
#         ]
        
#         # dispatch any output events
#         for output_event in output_events:
#             Event.dispatch(event=output_event, parent=event)
        
#         # trigger any callback events
#         if event.on_failure:
#             Event.dispatch(event=event.on_failure, parent=event)

