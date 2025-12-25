__package__ = 'archivebox.core'

import time
import os
from datetime import timedelta
from typing import ClassVar

from django.db.models import F
from django.utils import timezone

from rich import print

from statemachine import State, StateMachine

# from workers.actor import ActorType

from core.models import Snapshot, ArchiveResult
from crawls.models import Crawl, Seed


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
        
    def __repr__(self) -> str:
        return f'[grey53]Snapshot\\[{self.snapshot.id}] 🏃‍♂️ Worker\\[pid={os.getpid()}].tick()[/grey53] [blue]{self.snapshot.status.upper()}[/blue] ⚙️ [grey37]Machine[/grey37]'
    
    def __str__(self) -> str:
        return self.__repr__()
        
    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url)
        if not can_start:
            print(f'{self}.can_start() [blue]QUEUED[/blue] ➡️❌ [blue]STARTED[/blue] cant start yet +{timezone.now() - self.snapshot.retry_at}s')
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
        
    # def on_transition(self, event, state):
    #     print(f'{self}.on_transition() [blue]{str(state).upper()}[/blue] ➡️ ...')
        
    @queued.enter
    def enter_queued(self):
        print(f'{self}.on_queued() ↳ snapshot.retry_at = now()')
        self.snapshot.update_for_workers(
            retry_at=timezone.now(),
            status=Snapshot.StatusChoices.QUEUED,
        )
        
    @started.enter
    def enter_started(self):
        print(f'{self}.on_started() ↳ snapshot.run()')
        # lock the snapshot while we create the pending archiveresults
        self.snapshot.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),  # if failed, wait 30s before retrying
        )

        # Run the snapshot - creates pending archiveresults for all enabled extractors
        self.snapshot.run()

        # unlock the snapshot after we're done + set status = started
        self.snapshot.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=5),  # wait 5s before checking it again
            status=Snapshot.StatusChoices.STARTED,
        )
        
    @sealed.enter
    def enter_sealed(self):
        print(f'{self}.on_sealed() ↳ snapshot.retry_at=None')
        self.snapshot.update_for_workers(
            retry_at=None,
            status=Snapshot.StatusChoices.SEALED,
        )


# class SnapshotWorker(ActorType[Snapshot]):
#     """
#     The primary actor for progressing Snapshot objects
#     through their lifecycle using the SnapshotMachine.
#     """
#     Model = Snapshot
#     StateMachineClass = SnapshotMachine
    
#     ACTIVE_STATE: ClassVar[State] = SnapshotMachine.started                    # 'started'
    
#     MAX_CONCURRENT_ACTORS: ClassVar[int] = 3
#     MAX_TICK_TIME: ClassVar[int] = 10
#     CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10





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
    skipped = State(value=ArchiveResult.StatusChoices.SKIPPED, final=True)
    
    # Tick Event - transitions based on conditions
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed') |
        started.to(skipped, cond='is_skipped') |
        started.to(backoff, cond='is_backoff') |
        backoff.to.itself(unless='can_start') |
        backoff.to(started, cond='can_start') |
        backoff.to(succeeded, cond='is_succeeded') |
        backoff.to(failed, cond='is_failed') |
        backoff.to(skipped, cond='is_skipped')
    )

    def __init__(self, archiveresult, *args, **kwargs):
        self.archiveresult = archiveresult
        super().__init__(archiveresult, *args, **kwargs)
    
    def __repr__(self) -> str:
        return f'[grey53]ArchiveResult\\[{self.archiveresult.id}] 🏃‍♂️ Worker\\[pid={os.getpid()}].tick()[/grey53] [blue]{self.archiveresult.status.upper()}[/blue] ⚙️ [grey37]Machine[/grey37]'
    
    def __str__(self) -> str:
        return self.__repr__()
        
    def can_start(self) -> bool:
        can_start = bool(self.archiveresult.snapshot.url)
        if not can_start:
            print(f'{self}.can_start() [blue]QUEUED[/blue] ➡️❌ [blue]STARTED[/blue]: cant start yet +{timezone.now() - self.archiveresult.retry_at}s')
        return can_start
    
    def is_succeeded(self) -> bool:
        """Check if extraction succeeded (status was set by run_extractor())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED
    
    def is_failed(self) -> bool:
        """Check if extraction failed (status was set by run_extractor())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.FAILED
    
    def is_skipped(self) -> bool:
        """Check if extraction was skipped (status was set by run_extractor())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SKIPPED
    
    def is_backoff(self) -> bool:
        """Check if we should backoff and retry later."""
        # Backoff if status is still started (extractor didn't complete) and output is None
        return (
            self.archiveresult.status == ArchiveResult.StatusChoices.STARTED and 
            self.archiveresult.output is None
        )
    
    def is_finished(self) -> bool:
        """Check if extraction has completed (success, failure, or skipped)."""
        return self.archiveresult.status in (
            ArchiveResult.StatusChoices.SUCCEEDED,
            ArchiveResult.StatusChoices.FAILED,
            ArchiveResult.StatusChoices.SKIPPED,
        )

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
        print(f'{self}.on_started() ↳ archiveresult.start_ts + run_extractor()')
        
        # Lock the object and mark start time
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=120),  # 2 min timeout for extractor
            status=ArchiveResult.StatusChoices.STARTED,
            start_ts=timezone.now(),
        )
        
        # Run the extractor - this updates status, output, timestamps, etc.
        self.archiveresult.run()
        
        # Save the updated result
        self.archiveresult.save()
        
        # Log the result
        if self.archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED:
            print(f'{self} ✅ extractor succeeded: {self.archiveresult.output[:50] if self.archiveresult.output else ""}...')
        elif self.archiveresult.status == ArchiveResult.StatusChoices.FAILED:
            print(f'{self} ❌ extractor failed: {self.archiveresult.output[:100] if self.archiveresult.output else ""}...')
        elif self.archiveresult.status == ArchiveResult.StatusChoices.SKIPPED:
            print(f'{self} ⏭️ extractor skipped: {self.archiveresult.output[:50] if self.archiveresult.output else ""}')

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

        # Increment health stats on ArchiveResult, Snapshot, and optionally Crawl/Seed
        ArchiveResult.objects.filter(pk=self.archiveresult.pk).update(num_uses_succeeded=F('num_uses_succeeded') + 1)
        Snapshot.objects.filter(pk=self.archiveresult.snapshot_id).update(num_uses_succeeded=F('num_uses_succeeded') + 1)

        # Also update Crawl and Seed health stats if snapshot has a crawl
        snapshot = self.archiveresult.snapshot
        if snapshot.crawl_id:
            Crawl.objects.filter(pk=snapshot.crawl_id).update(num_uses_succeeded=F('num_uses_succeeded') + 1)
            crawl = Crawl.objects.filter(pk=snapshot.crawl_id).values_list('seed_id', flat=True).first()
            if crawl:
                Seed.objects.filter(pk=crawl).update(num_uses_succeeded=F('num_uses_succeeded') + 1)

    @failed.enter
    def enter_failed(self):
        print(f'{self}.on_failed() ↳ archiveresult.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.FAILED,
            end_ts=timezone.now(),
        )

        # Increment health stats on ArchiveResult, Snapshot, and optionally Crawl/Seed
        ArchiveResult.objects.filter(pk=self.archiveresult.pk).update(num_uses_failed=F('num_uses_failed') + 1)
        Snapshot.objects.filter(pk=self.archiveresult.snapshot_id).update(num_uses_failed=F('num_uses_failed') + 1)

        # Also update Crawl and Seed health stats if snapshot has a crawl
        snapshot = self.archiveresult.snapshot
        if snapshot.crawl_id:
            Crawl.objects.filter(pk=snapshot.crawl_id).update(num_uses_failed=F('num_uses_failed') + 1)
            crawl = Crawl.objects.filter(pk=snapshot.crawl_id).values_list('seed_id', flat=True).first()
            if crawl:
                Seed.objects.filter(pk=crawl).update(num_uses_failed=F('num_uses_failed') + 1)

    @skipped.enter
    def enter_skipped(self):
        print(f'{self}.on_skipped() ↳ archiveresult.retry_at = None, archiveresult.end_ts = now()')
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SKIPPED,
            end_ts=timezone.now(),
        )
        
    def after_transition(self, event: str, source: State, target: State):
        # print(f"after '{event}' from '{source.id}' to '{target.id}'")
        self.archiveresult.snapshot.update_for_workers()  # bump snapshot retry time so it picks up all the new changes


# class ArchiveResultWorker(ActorType[ArchiveResult]):
#     """
#     The primary actor for progressing ArchiveResult objects
#     through their lifecycle using the ArchiveResultMachine.
#     """
#     Model = ArchiveResult
#     StateMachineClass = ArchiveResultMachine
    
#     ACTIVE_STATE: ClassVar[State] = ArchiveResultMachine.started                # 'started'
    
#     MAX_CONCURRENT_ACTORS: ClassVar[int] = 6
#     MAX_TICK_TIME: ClassVar[int] = 60
#     CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10
