__package__ = 'archivebox.workers'

import os
import sys
import time
import uuid
import json
import unittest
from typing import ClassVar, Iterable, Type
from pathlib import Path

from rich import print

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.functional import classproperty       # type: ignore

from crawls.models import Seed, Crawl
from core.models import Snapshot, ArchiveResult

from workers.models import Event, Process, EventDict


class WorkerType:
    # static class attributes
    name: ClassVar[str]              # e.g. 'log' or 'filesystem' or 'crawl' or 'snapshot' or 'archiveresult' etc.
    
    listens_to: ClassVar[str]        # e.g. 'LOG_' or 'FS_' or 'CRAWL_' or 'SNAPSHOT_' or 'ARCHIVERESULT_' etc.
    outputs: ClassVar[list[str]]     # e.g. ['LOG_', 'FS_', 'CRAWL_', 'SNAPSHOT_', 'ARCHIVERESULT_'] etc.
    
    poll_interval: ClassVar[int] = 1     # how long to wait before polling for new events
    
    @classproperty
    def event_queue(cls) -> QuerySet[Event]:
        return Event.objects.filter(name__startswith=cls.listens_to)

    @classmethod
    def fork(cls, wait_for_first_event=False, exit_on_idle=True) -> Process:
        cmd = ['archivebox', 'worker', cls.name]
        if exit_on_idle:
            cmd.append('--exit-on-idle')
        if wait_for_first_event:
            cmd.append('--wait-for-first-event')
        return Process.create_and_fork(cmd=cmd, actor_type=cls.name)

    @classproperty
    def processes(cls) -> QuerySet[Process]:
        return Process.objects.filter(actor_type=cls.name)

    @classmethod
    def run(cls, wait_for_first_event=False, exit_on_idle=True):

        if wait_for_first_event:
            event = cls.event_queue.get_next_unclaimed()
            while not event:
                time.sleep(cls.poll_interval)
                event = cls.event_queue.get_next_unclaimed()

        while True:
            output_events = list(cls.process_next_event()) or list(cls.process_idle_tick())   # process next event, or tick if idle
            yield from output_events
            if not output_events:
                if exit_on_idle:
                    break
                else:
                    time.sleep(cls.poll_interval)

    @classmethod
    def process_next_event(cls) -> Iterable[EventDict]:
        event = cls.event_queue.get_next_unclaimed()
        output_events = []
        
        if not event:
            return []
        
        cls.mark_event_claimed(event)
        print(f'{cls.__name__}[{Process.current().pid}] {event}', file=sys.stderr)
        try:
            for output_event in cls.receive(event):
                output_events.append(output_event)
                yield output_event
            cls.mark_event_succeeded(event, output_events=output_events)
        except BaseException as e:
            cls.mark_event_failed(event, output_events=output_events, error=e)

    @classmethod
    def process_idle_tick(cls) -> Iterable[EventDict]:
        # reset the idle event to be claimed by the current process
        event, _created = Event.objects.update_or_create(
            name=f'{cls.listens_to}IDLE',
            emitted_by=Process.current(),
            defaults={
                'deliver_at': timezone.now(),
                'claimed_proc': None,
                'claimed_at': None,
                'finished_at': None,
                'error': None,
                'parent': None,
            },
        )
        
        # then process it like any other event
        yield from cls.process_next_event()

    @classmethod
    def receive(cls, event: Event) -> Iterable[EventDict]:
        handler_method = getattr(cls, f'on_{event.name}', None)
        if handler_method:
            yield from handler_method(event)
        else:
            raise Exception(f'No handler method for event: {event.name}')

    @staticmethod
    def on_IDLE() -> Iterable[EventDict]:
        return []
    
    @staticmethod
    def mark_event_claimed(event: Event):
        proc = Process.current()
        
        with transaction.atomic():
            claimed = Event.objects.filter(id=event.id, claimed_proc=None, claimed_at=None).update(claimed_proc=proc, claimed_at=timezone.now())
            event.refresh_from_db()
            if not claimed:
                raise Exception(f'Event already claimed by another process: {event.claimed_proc}')
            
            print(f'{self}.mark_event_claimed(): Claimed {event} ⛏️')
            
            # process_updated = Process.objects.filter(id=proc.id, active_event=None).update(active_event=event)
            # if not process_updated:
            #     raise Exception(f'Unable to update process.active_event: {proc}.active_event = {event}')

    @staticmethod
    def mark_event_succeeded(event: Event, output_events: Iterable[EventDict]):
        event.refresh_from_db()
        assert event.claimed_proc, f'Cannot mark event as succeeded if it is not claimed by a process: {event}'
        assert (event.claimed_proc == Process.current()), f'Cannot mark event as succeeded if it claimed by a different process: {event}.claimed_proc = {event.claimed_proc}, current_process = {Process.current()}'
        
        with transaction.atomic():
            updated = Event.objects.filter(id=event.id, claimed_proc=event.claimed_proc, claimed_at=event.claimed_at, finished_at=None).update(finished_at=timezone.now())
            event.refresh_from_db()
            if not updated:
                raise Exception(f'Event {event} failed to mark as succeeded, it was modified by another process: {event.claimed_proc}')

            # process_updated = Process.objects.filter(id=event.claimed_proc.id, active_event=event).update(active_event=None)
            # if not process_updated:
            #     raise Exception(f'Unable to unset process.active_event: {event.claimed_proc}.active_event = {event}')

        # dispatch any output events
        for output_event in output_events:
            Event.dispatch(event=output_event, parent=event)

        # trigger any callback events
        if event.on_success:
            Event.dispatch(event=event.on_success, parent=event)

    @staticmethod
    def mark_event_failed(event: Event, output_events: Iterable[EventDict]=(), error: BaseException | None = None):
        event.refresh_from_db()
        assert event.claimed_proc, f'Cannot mark event as failed if it is not claimed by a process: {event}'
        assert (event.claimed_proc == Process.current()), f'Cannot mark event as failed if it claimed by a different process: {event}.claimed_proc = {event.claimed_proc}, current_process = {Process.current()}'
        
        with transaction.atomic():
            updated = Event.objects.filter(id=event.id, claimed_proc=event.claimed_proc, claimed_at=event.claimed_at, finished_at=None).update(finished_at=timezone.now(), error=str(error))
            event.refresh_from_db()
            if not updated:
                raise Exception(f'Event {event} failed to mark as failed, it was modified by another process: {event.claimed_proc}')

            # process_updated = Process.objects.filter(id=event.claimed_proc.id, active_event=event).update(active_event=None)
            # if not process_updated:
            #     raise Exception(f'Unable to unset process.active_event: {event.claimed_proc}.active_event = {event}')

        
        # add dedicated error event to the output events
        if not event.name.endswith('_ERROR'):
            output_events = [
                *output_events,
                {'name': f'{event.name}_ERROR', 'msg': f'{type(error).__name__}: {error}'},
            ]
            
        # dispatch any output events
        for output_event in output_events:
            Event.dispatch(event=output_event, parent=event)
        
        # trigger any callback events
        if event.on_failure:
            Event.dispatch(event=event.on_failure, parent=event)




class OrchestratorWorker(WorkerType):
    name = 'orchestrator'
    listens_to = 'PROC_'
    outputs = ['PROC_']
    
    @staticmethod
    def on_PROC_IDLE() -> Iterable[EventDict]:
        # look through all Processes that are not yet launched and launch them
        to_launch = Process.objects.filter(launched_at=None).order_by('created_at').first()
        if not to_launch:
            return []
        
        yield {'name': 'PROC_LAUNCH', 'id': to_launch.id}
    
    @staticmethod
    def on_PROC_LAUNCH(event: Event) -> Iterable[EventDict]:
        process = Process.create_and_fork(**event.kwargs)
        yield {'name': 'PROC_LAUNCHED', 'process_id': process.id}
        
    @staticmethod
    def on_PROC_EXIT(event: Event) -> Iterable[EventDict]:
        process = Process.objects.get(id=event.process_id)
        process.kill()
        yield {'name': 'PROC_KILLED', 'process_id': process.id}
        
    @staticmethod
    def on_PROC_KILL(event: Event) -> Iterable[EventDict]:
        process = Process.objects.get(id=event.process_id)
        process.kill()
        yield {'name': 'PROC_KILLED', 'process_id': process.id}


class FileSystemWorker(WorkerType):
    name = 'filesystem'
    listens_to = 'FS_'
    outputs = ['FS_']

    @staticmethod
    def on_FS_IDLE(event: Event) -> Iterable[EventDict]:
        # check for tmp files that can be deleted
        for tmp_file in Path('/tmp').glob('archivebox/*'):
            yield {'name': 'FS_DELETE', 'path': str(tmp_file)}
            
    @staticmethod
    def on_FS_WRITE(event: Event) -> Iterable[EventDict]:
        with open(event.path, 'w') as f:
            f.write(event.content)
        yield {'name': 'FS_CHANGED', 'path': event.path}

    @staticmethod
    def on_FS_APPEND(event: Event) -> Iterable[EventDict]:
        with open(event.path, 'a') as f:
            f.write(event.content)
        yield {'name': 'FS_CHANGED', 'path': event.path}
        
    @staticmethod
    def on_FS_DELETE(event: Event) -> Iterable[EventDict]:
        os.remove(event.path)
        yield {'name': 'FS_CHANGED', 'path': event.path}
        
    @staticmethod
    def on_FS_RSYNC(event: Event) -> Iterable[EventDict]:
        os.system(f'rsync -av {event.src} {event.dst}')
        yield {'name': 'FS_CHANGED', 'path': event.dst}


class CrawlWorker(WorkerType):
    name = 'crawl'
    listens_to = 'CRAWL_'
    outputs = ['CRAWL_', 'FS_', 'SNAPSHOT_']

    @staticmethod
    def on_CRAWL_IDLE(event: Event) -> Iterable[EventDict]:
        # check for any stale crawls that can be started or sealed
        stale_crawl = Crawl.objects.filter(retry_at__lt=timezone.now()).first()
        if not stale_crawl:
            return []

        if stale_crawl.can_start():
            yield {'name': 'CRAWL_START', 'id': stale_crawl.id}
        
        elif stale_crawl.can_seal():
            yield {'name': 'CRAWL_SEAL', 'id': stale_crawl.id}
            
    @staticmethod
    def on_CRAWL_CREATE(event: Event) -> Iterable[EventDict]:
        crawl = Crawl.objects.create(id=event.id, **event)
        yield {'name': 'FS_WRITE', 'path': crawl.OUTPUT_DIR / 'index.json', 'content': json.dumps(crawl.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'CRAWL_UPDATED', 'id': crawl.id}
        
    @staticmethod
    def on_CRAWL_UPDATE(event: Event) -> Iterable[EventDict]:
        Crawl.objects.filter(id=event.id).update(**event)
        yield {'name': 'FS_WRITE', 'path': crawl.OUTPUT_DIR / 'index.json', 'content': json.dumps(crawl.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'CRAWL_UPDATED', 'id': crawl.id}
        
    @staticmethod
    def on_CRAWL_SEAL(event: Event) -> Iterable[EventDict]:
        crawl = Crawl.objects.filter(id=event.id, status=Crawl.StatusChoices.STARTED).first()
        if not crawl:
            return
        crawl.status = Crawl.StatusChoices.SEALED
        crawl.save()
        yield {'name': 'FS_WRITE', 'path': crawl.OUTPUT_DIR / 'index.json', 'content': json.dumps(crawl.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'CRAWL_UPDATED', 'id': crawl.id}
        
    @staticmethod
    def on_CRAWL_START(event: Event) -> Iterable[EventDict]:
        # create root snapshot
        crawl = Crawl.objects.get(id=event.crawl_id)
        new_snapshot_id = uuid.uuid4()
        yield {'name': 'SNAPSHOT_CREATE', 'id': new_snapshot_id, 'crawl_id': crawl.id, 'url': crawl.seed.uri}
        yield {'name': 'SNAPSHOT_START', 'id': new_snapshot_id}
        yield {'name': 'CRAWL_UPDATE', 'id': crawl.id, 'status': 'started', 'retry_at': None}


class SnapshotWorker(WorkerType):
    name = 'snapshot'
    listens_to = 'SNAPSHOT_'
    outputs = ['SNAPSHOT_', 'FS_']
    
    @staticmethod
    def on_SNAPSHOT_IDLE(event: Event) -> Iterable[EventDict]:
        # check for any snapshots that can be started or sealed
        snapshot = Snapshot.objects.exclude(status=Snapshot.StatusChoices.SEALED).first()
        if not snapshot:
            return []
        
        if snapshot.can_start():
            yield {'name': 'SNAPSHOT_START', 'id': snapshot.id}
        elif snapshot.can_seal():
            yield {'name': 'SNAPSHOT_SEAL', 'id': snapshot.id}
            
    @staticmethod
    def on_SNAPSHOT_CREATE(event: Event) -> Iterable[EventDict]:
        snapshot = Snapshot.objects.create(id=event.snapshot_id, **event.kwargs)
        yield {'name': 'FS_WRITE', 'path': snapshot.OUTPUT_DIR / 'index.json', 'content': json.dumps(snapshot.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'SNAPSHOT_UPDATED', 'id': snapshot.id}
    
    @staticmethod
    def on_SNAPSHOT_SEAL(event: Event) -> Iterable[EventDict]:
        snapshot = Snapshot.objects.get(id=event.snapshot_id, status=Snapshot.StatusChoices.STARTED)
        assert snapshot.can_seal()
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save()
        yield {'name': 'FS_WRITE', 'path': snapshot.OUTPUT_DIR / 'index.json', 'content': json.dumps(snapshot.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'SNAPSHOT_UPDATED', 'id': snapshot.id}

    @staticmethod
    def on_SNAPSHOT_START(event: Event) -> Iterable[EventDict]:
        snapshot = Snapshot.objects.get(id=event.snapshot_id, status=Snapshot.StatusChoices.QUEUED)
        assert snapshot.can_start()
        
        # create pending archiveresults for each extractor
        for extractor in snapshot.get_extractors():
            new_archiveresult_id = uuid.uuid4()
            yield {'name': 'ARCHIVERESULT_CREATE', 'id': new_archiveresult_id, 'snapshot_id': snapshot.id, 'extractor': extractor.name}
            yield {'name': 'ARCHIVERESULT_START', 'id': new_archiveresult_id}
            
        snapshot.status = Snapshot.StatusChoices.STARTED
        snapshot.save()
        yield {'name': 'FS_WRITE', 'path': snapshot.OUTPUT_DIR / 'index.json', 'content': json.dumps(snapshot.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'SNAPSHOT_UPDATED', 'id': snapshot.id}
        
        

class ArchiveResultWorker(WorkerType):
    name = 'archiveresult'
    listens_to = 'ARCHIVERESULT_'
    outputs = ['ARCHIVERESULT_', 'FS_']


    @staticmethod
    def on_ARCHIVERESULT_UPDATE(event: Event) -> Iterable[EventDict]:
        ArchiveResult.objects.filter(id=event.id).update(**event.kwargs)
        archiveresult = ArchiveResult.objects.get(id=event.id)
        yield {'name': 'FS_WRITE', 'path': archiveresult.OUTPUT_DIR / f'{archiveresult.ABID}.json', 'content': json.dumps(archiveresult.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'ARCHIVERESULT_UPDATED', 'id': archiveresult.id}
        
    @staticmethod
    def on_ARCHIVERESULT_CREATE(event: Event) -> Iterable[EventDict]:
        archiveresult = ArchiveResult.objects.create(id=event.id, **event)
        yield {'name': 'ARCHIVERESULT_UPDATE', 'id': archiveresult.id}

    @staticmethod
    def on_ARCHIVERESULT_SEAL(event: Event) -> Iterable[EventDict]:
        archiveresult = ArchiveResult.objects.get(id=event.id, status=ArchiveResult.StatusChoices.STARTED)
        
        yield {'name': 'ARCHIVERESULT_UPDATE', 'id': archiveresult.id, 'status': 'sealed', 'on_success': {
            'name': 'FS_RSYNC', 'src': archiveresult.OUTPUT_DIR, 'dst': archiveresult.snapshot.OUTPUT_DIR, 'await_event_id': update_id,
        }}

    @staticmethod
    def on_ARCHIVERESULT_START(event: Event) -> Iterable[EventDict]:
        archiveresult = ArchiveResult.objects.get(id=event.id, status=ArchiveResult.StatusChoices.QUEUED)

        yield {
            'name': 'SHELL_EXEC',
            'cmd': archiveresult.EXTRACTOR.get_cmd(),
            'cwd': archiveresult.OUTPUT_DIR,
            'on_exit': {
                'name': 'ARCHIVERESULT_SEAL',
                'id': archiveresult.id,
            },
        }
        
        archiveresult.status = ArchiveResult.StatusChoices.STARTED
        archiveresult.save()
        yield {'name': 'FS_WRITE', 'path': archiveresult.OUTPUT_DIR / 'index.json', 'content': json.dumps(archiveresult.as_json(), default=str, indent=4, sort_keys=True)}
        yield {'name': 'ARCHIVERESULT_UPDATED', 'id': archiveresult.id}
        
    @staticmethod
    def on_ARCHIVERESULT_IDLE(event: Event) -> Iterable[EventDict]:
        stale_archiveresult = ArchiveResult.objects.exclude(status__in=[ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.FAILED]).first()
        if not stale_archiveresult:
            return []
        if stale_archiveresult.can_start():
            yield {'name': 'ARCHIVERESULT_START', 'id': stale_archiveresult.id}
        if stale_archiveresult.can_seal():
            yield {'name': 'ARCHIVERESULT_SEAL', 'id': stale_archiveresult.id}


WORKER_TYPES = [
    OrchestratorWorker,
    FileSystemWorker,
    CrawlWorker,
    SnapshotWorker,
    ArchiveResultWorker,
]

def get_worker_type(name: str) -> Type[WorkerType]:
    for worker_type in WORKER_TYPES:
        matches_verbose_name = (worker_type.name == name)
        matches_class_name = (worker_type.__name__.lower() == name.lower())
        matches_listens_to = (worker_type.listens_to.strip('_').lower() == name.strip('_').lower())
        if matches_verbose_name or matches_class_name or matches_listens_to:
            return worker_type
    raise Exception(f'Worker type not found: {name}')
