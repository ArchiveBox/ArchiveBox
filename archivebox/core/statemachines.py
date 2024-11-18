__package__ = 'archivebox.core'

import time
from datetime import timedelta
from typing import ClassVar

from django.utils import timezone

from statemachine import State, StateMachine

from actors.actor import ActorType

from core.models import Snapshot, ArchiveResult


class SnapshotMachine(StateMachine, strict_states=True):
    """
    State machine for managing Snapshot lifecycle.
    
    https://github.com/ArchiveBox/ArchiveBox/wiki/ArchiveBox-Architecture-Diagrams
    """
    
    model: Snapshot
    
    # States
    queued = State(value=Snapshot.StatusChoices.QUEUED, initial=True)
    started = State(value=Snapshot.StatusChoices.STARTED)
    sealed = State(value=Snapshot.StatusChoices.SEALED, final=True)
    
    # Tick Event
    tick = (
        queued.to.itself(unless='can_start', internal=True) |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished', internal=True) |
        started.to(sealed, cond='is_finished')
    )
    
    def __init__(self, snapshot, *args, **kwargs):
        self.snapshot = snapshot
        super().__init__(snapshot, *args, **kwargs)
        
    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url and (self.snapshot.retry_at < timezone.now()))
        if not can_start:
            print(f'SnapshotMachine[{self.snapshot.ABID}].can_start() False: {self.snapshot.url} {self.snapshot.retry_at} {timezone.now()}')
        return can_start
        
    def is_finished(self) -> bool:
        # if no archiveresults exist yet, it's not finished
        if not self.snapshot.archiveresult_set.exists():
            return False
        
        # if archiveresults exist but are still pending, it's not finished
        if self.snapshot.pending_archiveresults().exists():
            return False
        
        # otherwise archiveresults exist and are all finished, so it's finished
        return True
        
    def on_transition(self, event, state):
        print(f'SnapshotMachine[{self.snapshot.ABID}].on_transition() {event} -> {state}')
        
    @queued.enter
    def enter_queued(self):
        print(f'SnapshotMachine[{self.snapshot.ABID}].on_queued(): snapshot.retry_at = now()')
        self.snapshot.status = Snapshot.StatusChoices.QUEUED
        self.snapshot.retry_at = timezone.now()
        self.snapshot.save()
        
    @started.enter
    def enter_started(self):
        print(f'SnapshotMachine[{self.snapshot.ABID}].on_started(): snapshot.create_pending_archiveresults() + snapshot.bump_retry_at(+60s)')
        self.snapshot.bump_retry_at(seconds=30)                 # if failed, wait 10s before retrying
        self.snapshot.save()
        self.snapshot.create_pending_archiveresults()
        self.snapshot.status = Snapshot.StatusChoices.STARTED
        
    @sealed.enter
    def enter_sealed(self):
        print(f'SnapshotMachine[{self.snapshot.ABID}].on_sealed(): snapshot.retry_at=None')
        self.snapshot.status = Snapshot.StatusChoices.SEALED
        self.snapshot.retry_at = None
        self.snapshot.save()


class SnapshotWorker(ActorType[Snapshot]):
    """
    The primary actor for progressing Snapshot objects
    through their lifecycle using the SnapshotMachine.
    """
    Model = Snapshot
    StateMachineClass = SnapshotMachine
    
    ACTIVE_STATE: ClassVar[State] = SnapshotMachine.started                    # 'started'
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 3
    MAX_TICK_TIME: ClassVar[int] = 10
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10





class ArchiveResultMachine(StateMachine, strict_states=True):
    """
    State machine for managing ArchiveResult lifecycle.
    
    https://github.com/ArchiveBox/ArchiveBox/wiki/ArchiveBox-Architecture-Diagrams
    """
    
    model: ArchiveResult
    
    # States
    queued = State(value=ArchiveResult.StatusChoices.QUEUED, initial=True)
    started = State(value=ArchiveResult.StatusChoices.STARTED)
    backoff = State(value=ArchiveResult.StatusChoices.BACKOFF)
    succeeded = State(value=ArchiveResult.StatusChoices.SUCCEEDED, final=True)
    failed = State(value=ArchiveResult.StatusChoices.FAILED, final=True)
    
    # Tick Event
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed') |
        started.to(backoff, cond='is_backoff') |
        backoff.to.itself(unless='can_start') |
        backoff.to(started, cond='can_start') |
        backoff.to(succeeded, cond='is_succeeded') |
        backoff.to(failed, cond='is_failed')
    )

    def __init__(self, archiveresult, *args, **kwargs):
        self.archiveresult = archiveresult
        super().__init__(archiveresult, *args, **kwargs)
        
    def can_start(self) -> bool:
        return self.archiveresult.snapshot and (self.archiveresult.retry_at < timezone.now())
    
    def is_succeeded(self) -> bool:
        if self.archiveresult.output and 'err' not in self.archiveresult.output.lower():
            return True
        return False
    
    def is_failed(self) -> bool:
        if self.archiveresult.output and 'err' in self.archiveresult.output.lower():
            return True
        return False
    
    def is_backoff(self) -> bool:
        if self.archiveresult.output is None:
            return True
        return False
    
    def is_finished(self) -> bool:
        return self.is_failed() or self.is_succeeded()
    

    @queued.enter
    def enter_queued(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_queued(): archiveresult.retry_at = now()')
        self.archiveresult.update_for_workers(
            retry_at=timezone.now(),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=None,
        )  # bump the snapshot's retry_at so they pickup any new changes
        
    @started.enter
    def enter_started(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_started(): archiveresult.start_ts + create_output_dir() + bump_retry_at(+60s)')
        # lock the object for the next 30sec
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=timezone.now(),
        )   # lock the obj for the next ~30s to limit racing with other workers
        
        # create the output directory and fork the new extractor job subprocess
        self.archiveresult.create_output_dir()
        # self.archiveresult.extract(background=True)
        
        # mark the object as started
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),       # retry it again in 30s if it fails
            status=ArchiveResult.StatusChoices.STARTED,
        )
        
        # simulate slow running extractor that completes after 2 seconds
        time.sleep(2)
        self.archiveresult.update_for_workers(output='completed')

    @backoff.enter
    def enter_backoff(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_backoff(): archiveresult.retries += 1, archiveresult.bump_retry_at(+60s), archiveresult.end_ts = None')
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=60),
            status=ArchiveResult.StatusChoices.BACKOFF,
            end_ts=None,
            # retries=F('retries') + 1,               # F() equivalent to getattr(self.archiveresult, 'retries', 0) + 1,
        )
        self.archiveresult.save(write_indexes=True)
        
    @succeeded.enter
    def enter_succeeded(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_succeeded(): archiveresult.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            end_ts=timezone.now(),
            # **self.archiveresult.get_output_dict(),     # {output, output_json, stderr, stdout, returncode, errors, cmd_version, pwd, cmd, machine}
        )
        self.archiveresult.save(write_indexes=True)

    @failed.enter
    def enter_failed(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_failed(): archivebox.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.FAILED,
            end_ts=timezone.now(),
            # **self.archiveresult.get_output_dict(),     # {output, output_json, stderr, stdout, returncode, errors, cmd_version, pwd, cmd, machine}
        )
        
    def after_transition(self, event: str, source: State, target: State):
        # print(f"after '{event}' from '{source.id}' to '{target.id}'")
        self.archiveresult.snapshot.update_for_workers()  # bump snapshot retry time so it picks up all the new changes


class ArchiveResultWorker(ActorType[ArchiveResult]):
    """
    The primary actor for progressing ArchiveResult objects
    through their lifecycle using the ArchiveResultMachine.
    """
    Model = ArchiveResult
    StateMachineClass = ArchiveResultMachine
    
    ACTIVE_STATE: ClassVar[State] = ArchiveResultMachine.started                # 'started'
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 6
    MAX_TICK_TIME: ClassVar[int] = 60
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10
