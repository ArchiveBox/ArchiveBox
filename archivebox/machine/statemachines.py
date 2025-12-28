__package__ = 'archivebox.machine'

from datetime import timedelta
from django.utils import timezone
from django.db.models import F

from statemachine import State, StateMachine

from machine.models import Binary


class BinaryMachine(StateMachine, strict_states=True):
    """
    State machine for managing Binary installation lifecycle.

    Follows the unified pattern used by Crawl, Snapshot, and ArchiveResult:
    - queued: Binary needs to be installed
    - started: Installation hooks are running
    - succeeded: Binary installed successfully (abspath, version, sha256 populated)
    - failed: Installation failed permanently
    """

    model: Binary

    # States
    queued = State(value=Binary.StatusChoices.QUEUED, initial=True)
    started = State(value=Binary.StatusChoices.STARTED)
    succeeded = State(value=Binary.StatusChoices.SUCCEEDED, final=True)
    failed = State(value=Binary.StatusChoices.FAILED, final=True)

    # Tick Event - transitions based on conditions
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed')
    )

    def __init__(self, binary, *args, **kwargs):
        self.binary = binary
        super().__init__(binary, *args, **kwargs)

    def __repr__(self) -> str:
        return f'Binary[{self.binary.id}]'

    def __str__(self) -> str:
        return self.__repr__()

    def can_start(self) -> bool:
        """Check if binary installation can start."""
        return bool(self.binary.name and self.binary.binproviders)

    def is_succeeded(self) -> bool:
        """Check if installation succeeded (status was set by run())."""
        return self.binary.status == Binary.StatusChoices.SUCCEEDED

    def is_failed(self) -> bool:
        """Check if installation failed (status was set by run())."""
        return self.binary.status == Binary.StatusChoices.FAILED

    def is_finished(self) -> bool:
        """Check if installation has completed (success or failure)."""
        return self.binary.status in (
            Binary.StatusChoices.SUCCEEDED,
            Binary.StatusChoices.FAILED,
        )

    @queued.enter
    def enter_queued(self):
        """Binary is queued for installation."""
        self.binary.update_for_workers(
            retry_at=timezone.now(),
            status=Binary.StatusChoices.QUEUED,
        )

    @started.enter
    def enter_started(self):
        """Start binary installation."""
        # Lock the binary while installation runs
        self.binary.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=300),  # 5 min timeout for installation
            status=Binary.StatusChoices.STARTED,
        )

        # Run installation hooks
        self.binary.run()

        # Save updated status (run() updates status to succeeded/failed)
        self.binary.save()

    @succeeded.enter
    def enter_succeeded(self):
        """Binary installed successfully."""
        self.binary.update_for_workers(
            retry_at=None,
            status=Binary.StatusChoices.SUCCEEDED,
        )

        # Increment health stats
        Binary.objects.filter(pk=self.binary.pk).update(num_uses_succeeded=F('num_uses_succeeded') + 1)

    @failed.enter
    def enter_failed(self):
        """Binary installation failed."""
        self.binary.update_for_workers(
            retry_at=None,
            status=Binary.StatusChoices.FAILED,
        )

        # Increment health stats
        Binary.objects.filter(pk=self.binary.pk).update(num_uses_failed=F('num_uses_failed') + 1)
