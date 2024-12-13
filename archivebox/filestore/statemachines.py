__package__ = 'archivebox.filestore'

import time
import os
from datetime import timedelta
from typing import ClassVar

from django.utils import timezone

from rich import print

from statemachine import State, StateMachine

from workers.actor import ActorType

from .models import File

class FileMachine(StateMachine, strict_states=True):
    """
    State machine for managing File lifecycle.

    https://github.com/ArchiveBox/ArchiveBox/wiki/ArchiveBox-Architecture-Diagrams
    """
    
    model: File
    MAX_LOCK_TIME: ClassVar[int] = 600
    
    # States
    unlocked = State(value=File.StatusChoices.UNLOCKED, initial=True)
    locked = State(value=File.StatusChoices.LOCKED)
    
    # Transition Events
    lock = unlocked.to(locked, cond='can_lock')
    unlock = locked.to(unlocked)
    
    
    def __init__(self, file, *args, **kwargs):
        self.file = file
        super().__init__(file, *args, **kwargs)
        
    def __repr__(self) -> str:
        return f'[grey53]File\\[{self.file.ABID}] 🏃‍♂️ Worker\\[pid={os.getpid()}].tick()[/grey53] [blue]{self.file.status.upper()}[/blue] ⚙️ [grey37]Machine[/grey37]'
    
    def __str__(self) -> str:
        return self.__repr__()
    
    @locked.enter
    def enter_locked(self):
        print(f'{self}.on_locked() ↳ file.locked_at = now()')
        self.file.lock_file(seconds=self.MAX_LOCK_TIME)
        
    def can_lock(self) -> bool:
        return self.file.status == File.StatusChoices.UNLOCKED
        

class FileWorker(ActorType[File]):
    """
    The primary actor for progressing Snapshot objects
    through their lifecycle using the SnapshotMachine.
    """
    Model = File
    StateMachineClass = FileMachine
    
    ACTIVE_STATE: ClassVar[State] = FileMachine.locked
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 4
    MAX_TICK_TIME: ClassVar[int] = 600
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
    
    def __repr__(self) -> str:
        return f'[grey53]ArchiveResult\\[{self.archiveresult.ABID}] 🏃‍♂️ Worker\\[pid={os.getpid()}].tick()[/grey53] [blue]{self.archiveresult.status.upper()}[/blue] ⚙️ [grey37]Machine[/grey37]'
    
    def __str__(self) -> str:
        return self.__repr__()
        
    def can_start(self) -> bool:
        can_start = bool(self.archiveresult.snapshot.url)
        if not can_start:
            print(f'{self}.can_start() [blue]QUEUED[/blue] ➡️❌ [blue]STARTED[/blue]: cant start yet +{timezone.now() - self.archiveresult.retry_at}s')
        return can_start
    
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
        print(f'{self}.on_queued() ↳ archiveresult.retry_at = now()')
        self.archiveresult.update_for_workers(
            retry_at=timezone.now(),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=None,
        )  # bump the snapshot's retry_at so they pickup any new changes
        
    @started.enter
    def enter_started(self):
        print(f'{self}.on_started() ↳ archiveresult.start_ts + create_output_dir() + bump_retry_at(+60s)')
        # lock the object for the next 30sec
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=timezone.now(),
        )   # lock the obj for the next ~30s to limit racing with other workers
        
        # run_subcommand([
        #     'archivebox', 'extract', self.archiveresult.ABID,
        # ])
        
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
        print(f'{self}.on_backoff() ↳ archiveresult.retries += 1, archiveresult.bump_retry_at(+60s), archiveresult.end_ts = None')
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=60),
            status=ArchiveResult.StatusChoices.BACKOFF,
            end_ts=None,
            # retries=F('retries') + 1,               # F() equivalent to getattr(self.archiveresult, 'retries', 0) + 1,
        )
        self.archiveresult.save(write_indexes=True)
        
    @succeeded.enter
    def enter_succeeded(self):
        print(f'{self}.on_succeeded() ↳ archiveresult.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            end_ts=timezone.now(),
            # **self.archiveresult.get_output_dict(),     # {output, output_json, stderr, stdout, returncode, errors, cmd_version, pwd, cmd, machine}
        )
        self.archiveresult.save(write_indexes=True)

    @failed.enter
    def enter_failed(self):
        print(f'{self}.on_failed() ↳ archiveresult.retry_at = None, archiveresult.end_ts = now()')
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
