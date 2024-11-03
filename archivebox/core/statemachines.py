__package__ = 'archivebox.snapshots'

from django.utils import timezone

from statemachine import State, StateMachine

from core.models import Snapshot, ArchiveResult

# State Machine Definitions
#################################################


class SnapshotMachine(StateMachine, strict_states=True):
    """State machine for managing Snapshot lifecycle."""
    
    model: Snapshot
    
    # States
    queued = State(value=Snapshot.SnapshotStatus.QUEUED, initial=True)
    started = State(value=Snapshot.SnapshotStatus.STARTED)
    sealed = State(value=Snapshot.SnapshotStatus.SEALED, final=True)
    
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
        return self.snapshot.seed and self.snapshot.seed.uri
        
    def is_finished(self) -> bool:
        return not self.snapshot.has_pending_archiveresults()
        
    def on_started(self):
        self.snapshot.create_pending_archiveresults()
        self.snapshot.bump_retry_at(seconds=60)
        self.snapshot.save()
        
    def on_sealed(self):
        self.snapshot.retry_at = None
        self.snapshot.save()

class ArchiveResultMachine(StateMachine, strict_states=True):
    """State machine for managing ArchiveResult lifecycle."""
    
    model: ArchiveResult
    
    # States
    queued = State(value=ArchiveResult.ArchiveResultStatus.QUEUED, initial=True)
    started = State(value=ArchiveResult.ArchiveResultStatus.STARTED)
    backoff = State(value=ArchiveResult.ArchiveResultStatus.BACKOFF)
    succeeded = State(value=ArchiveResult.ArchiveResultStatus.SUCCEEDED, final=True)
    failed = State(value=ArchiveResult.ArchiveResultStatus.FAILED, final=True)
    
    # Tick Event
    tick = (
        queued.to.itself(unless='can_start', internal=True) |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished', internal=True) |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed') |
        started.to(backoff, cond='is_backoff') |
        backoff.to.itself(unless='can_start', internal=True) |
        backoff.to(started, cond='can_start') |
        backoff.to(succeeded, cond='is_succeeded') |
        backoff.to(failed, cond='is_failed')
    )

    def __init__(self, archiveresult, *args, **kwargs):
        self.archiveresult = archiveresult
        super().__init__(archiveresult, *args, **kwargs)
        
    def can_start(self) -> bool:
        return self.archiveresult.snapshot and self.archiveresult.snapshot.is_started()
    
    def is_succeeded(self) -> bool:
        return self.archiveresult.output_exists()
    
    def is_failed(self) -> bool:
        return not self.archiveresult.output_exists()
    
    def is_backoff(self) -> bool:
        return self.archiveresult.status == ArchiveResult.ArchiveResultStatus.BACKOFF

    def on_started(self):
        self.archiveresult.start_ts = timezone.now()
        self.archiveresult.create_output_dir()
        self.archiveresult.bump_retry_at(seconds=60)
        self.archiveresult.save()

    def on_backoff(self):
        self.archiveresult.bump_retry_at(seconds=60)
        self.archiveresult.save()

    def on_succeeded(self):
        self.archiveresult.end_ts = timezone.now()
        self.archiveresult.save()

    def on_failed(self):
        self.archiveresult.end_ts = timezone.now()
        self.archiveresult.save()
        
    def after_transition(self, event: str, source: State, target: State):
        print(f"after '{event}' from '{source.id}' to '{target.id}'")
        # self.archiveresult.save_merkle_index()
        # self.archiveresult.save_html_index()
        # self.archiveresult.save_json_index()
        return "after_transition"
