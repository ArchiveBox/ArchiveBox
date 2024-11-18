__package__ = 'archivebox.snapshots'

import time

from django.utils import timezone

from statemachine import State, StateMachine

from core.models import Snapshot, ArchiveResult

# State Machine Definitions
#################################################


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
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
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
        self.snapshot.status = Snapshot.StatusChoices.STARTED
        self.snapshot.bump_retry_at(seconds=2)
        self.snapshot.save()
        self.snapshot.create_pending_archiveresults()
        
    @sealed.enter
    def enter_sealed(self):
        print(f'SnapshotMachine[{self.snapshot.ABID}].on_sealed(): snapshot.retry_at=None')
        self.snapshot.status = Snapshot.StatusChoices.SEALED
        self.snapshot.retry_at = None
        self.snapshot.save()


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
        self.archiveresult.status = ArchiveResult.StatusChoices.QUEUED
        self.archiveresult.retry_at = timezone.now()
        self.archiveresult.save()
        
    @started.enter
    def enter_started(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_started(): archiveresult.start_ts + create_output_dir() + bump_retry_at(+60s)')
        self.archiveresult.status = ArchiveResult.StatusChoices.STARTED
        self.archiveresult.start_ts = timezone.now()
        self.archiveresult.bump_retry_at(seconds=2)
        self.archiveresult.save()
        self.archiveresult.create_output_dir()
        time.sleep(2)
        self.archiveresult.output = 'completed'
        self.archiveresult.save()

    @backoff.enter
    def enter_backoff(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_backoff(): archiveresult.retries += 1, archiveresult.bump_retry_at(+60s), archiveresult.end_ts = None')
        self.archiveresult.status = ArchiveResult.StatusChoices.BACKOFF
        self.archiveresult.retries = getattr(self.archiveresult, 'retries', 0) + 1
        self.archiveresult.bump_retry_at(seconds=2)
        self.archiveresult.end_ts = None
        self.archiveresult.save()
        
    @succeeded.enter
    def enter_succeeded(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_succeeded(): archiveresult.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.status = ArchiveResult.StatusChoices.SUCCEEDED
        self.archiveresult.retry_at = None
        self.archiveresult.end_ts = timezone.now()
        self.archiveresult.save()

    @failed.enter
    def enter_failed(self):
        print(f'ArchiveResultMachine[{self.archiveresult.ABID}].on_failed(): archivebox.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.status = ArchiveResult.StatusChoices.FAILED
        self.archiveresult.retry_at = None
        self.archiveresult.end_ts = timezone.now()
        self.archiveresult.save()
        
    # def after_transition(self, event: str, source: State, target: State):
    #     print(f"after '{event}' from '{source.id}' to '{target.id}'")
    #     # self.archiveresult.save_merkle_index()
    #     # self.archiveresult.save_html_index()
    #     # self.archiveresult.save_json_index()
    #     return "after_transition"
