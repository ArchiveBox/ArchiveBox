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
from crawls.models import Crawl


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
        return f'Snapshot[{self.snapshot.id}]'

    def __str__(self) -> str:
        return self.__repr__()

    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url)
        # Suppressed: queue waiting logs
        return can_start
        
    def is_finished(self) -> bool:
        # if no archiveresults exist yet, it's not finished
        if not self.snapshot.archiveresult_set.exists():
            return False

        # if archiveresults exist but are still pending, it's not finished
        if self.snapshot.pending_archiveresults().exists():
            return False

        # Don't wait for background hooks - they'll be cleaned up on entering sealed state
        # Background hooks in STARTED state are excluded by pending_archiveresults()
        # (STARTED is in FINAL_OR_ACTIVE_STATES) so once all results are FINAL or ACTIVE,
        # we can transition to sealed and cleanup() will kill the background hooks

        # otherwise archiveresults exist and are all finished, so it's finished
        return True
        
    # def on_transition(self, event, state):
    #     print(f'{self}.on_transition() [blue]{str(state).upper()}[/blue] ➡️ ...')
        
    @queued.enter
    def enter_queued(self):
        # Suppressed: state transition logs
        self.snapshot.update_for_workers(
            retry_at=timezone.now(),
            status=Snapshot.StatusChoices.QUEUED,
        )

    @started.enter
    def enter_started(self):
        # Suppressed: state transition logs
        # lock the snapshot while we create the pending archiveresults
        self.snapshot.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),  # if failed, wait 30s before retrying
        )

        # Run the snapshot - creates pending archiveresults for all enabled plugins
        self.snapshot.run()

        # unlock the snapshot after we're done + set status = started
        self.snapshot.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=5),  # check again in 5s
            status=Snapshot.StatusChoices.STARTED,
        )

    @sealed.enter
    def enter_sealed(self):
        # Clean up background hooks
        self.snapshot.cleanup()

        # Suppressed: state transition logs
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
        return f'ArchiveResult[{self.archiveresult.id}]'

    def __str__(self) -> str:
        return self.__repr__()

    def can_start(self) -> bool:
        can_start = bool(self.archiveresult.snapshot.url)
        # Suppressed: queue waiting logs
        return can_start
    
    def is_succeeded(self) -> bool:
        """Check if extractor plugin succeeded (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED

    def is_failed(self) -> bool:
        """Check if extractor plugin failed (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.FAILED

    def is_skipped(self) -> bool:
        """Check if extractor plugin was skipped (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SKIPPED
    
    def is_backoff(self) -> bool:
        """Check if we should backoff and retry later."""
        # Backoff if status is still started (plugin didn't complete) and output_str is empty
        return (
            self.archiveresult.status == ArchiveResult.StatusChoices.STARTED and
            not self.archiveresult.output_str
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
        # Suppressed: state transition logs
        self.archiveresult.update_for_workers(
            retry_at=timezone.now(),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=None,
        )  # bump the snapshot's retry_at so they pickup any new changes

    @started.enter
    def enter_started(self):
        from machine.models import NetworkInterface

        # Suppressed: state transition logs
        # Lock the object and mark start time
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=120),  # 2 min timeout for plugin
            status=ArchiveResult.StatusChoices.STARTED,
            start_ts=timezone.now(),
            iface=NetworkInterface.current(),
        )

        # Run the plugin - this updates status, output, timestamps, etc.
        self.archiveresult.run()

        # Save the updated result
        self.archiveresult.save()

        # Suppressed: plugin result logs (already logged by worker)

    @backoff.enter
    def enter_backoff(self):
        # Suppressed: state transition logs
        self.archiveresult.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=60),
            status=ArchiveResult.StatusChoices.BACKOFF,
            end_ts=None,
            # retries=F('retries') + 1,               # F() equivalent to getattr(self.archiveresult, 'retries', 0) + 1,
        )
        self.archiveresult.save()

    @succeeded.enter
    def enter_succeeded(self):
        # Suppressed: state transition logs
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            end_ts=timezone.now(),
            # **self.archiveresult.get_output_dict(),     # {output, output_json, stderr, stdout, returncode, errors, cmd_version, pwd, cmd, machine}
        )
        self.archiveresult.save()

        # Increment health stats on ArchiveResult, Snapshot, and optionally Crawl
        ArchiveResult.objects.filter(pk=self.archiveresult.pk).update(num_uses_succeeded=F('num_uses_succeeded') + 1)
        Snapshot.objects.filter(pk=self.archiveresult.snapshot_id).update(num_uses_succeeded=F('num_uses_succeeded') + 1)

        # Also update Crawl health stats if snapshot has a crawl
        snapshot = self.archiveresult.snapshot
        if snapshot.crawl_id:
            Crawl.objects.filter(pk=snapshot.crawl_id).update(num_uses_succeeded=F('num_uses_succeeded') + 1)

    @failed.enter
    def enter_failed(self):
        # Suppressed: state transition logs
        self.archiveresult.update_for_workers(
            retry_at=None,
            status=ArchiveResult.StatusChoices.FAILED,
            end_ts=timezone.now(),
        )

        # Increment health stats on ArchiveResult, Snapshot, and optionally Crawl
        ArchiveResult.objects.filter(pk=self.archiveresult.pk).update(num_uses_failed=F('num_uses_failed') + 1)
        Snapshot.objects.filter(pk=self.archiveresult.snapshot_id).update(num_uses_failed=F('num_uses_failed') + 1)

        # Also update Crawl health stats if snapshot has a crawl
        snapshot = self.archiveresult.snapshot
        if snapshot.crawl_id:
            Crawl.objects.filter(pk=snapshot.crawl_id).update(num_uses_failed=F('num_uses_failed') + 1)

    @skipped.enter
    def enter_skipped(self):
        # Suppressed: state transition logs
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
