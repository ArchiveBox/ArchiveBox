__package__ = 'archivebox.core'

from typing import ClassVar

from statemachine import State

from core.models import Snapshot, ArchiveResult
from core.statemachines import SnapshotMachine, ArchiveResultMachine
from actors.actor import ActorType


class SnapshotActor(ActorType[Snapshot]):
    """
    The primary actor for progressing Snapshot objects
    through their lifecycle using the SnapshotMachine.
    """
    Model = Snapshot
    StateMachineClass = SnapshotMachine
    
    ACTIVE_STATE: ClassVar[State] = SnapshotMachine.started                    # 'started'
    FINAL_STATES: ClassVar[list[State]] = SnapshotMachine.final_states         # ['sealed']
    STATE_FIELD_NAME: ClassVar[str] = Snapshot.state_field_name                # status
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 3
    MAX_TICK_TIME: ClassVar[int] = 10
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10



class ArchiveResultActor(ActorType[ArchiveResult]):
    """
    The primary actor for progressing ArchiveResult objects
    through their lifecycle using the ArchiveResultMachine.
    """
    Model = ArchiveResult
    StateMachineClass = ArchiveResultMachine
    
    ACTIVE_STATE: ClassVar[State] = ArchiveResultMachine.started                # 'started'
    FINAL_STATES: ClassVar[list[State]] = ArchiveResultMachine.final_states     # ['succeeded', 'failed', 'skipped']
    STATE_FIELD_NAME: ClassVar[str] = ArchiveResult.state_field_name            # status
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 6
    MAX_TICK_TIME: ClassVar[int] = 60
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10

    # @classproperty
    # def qs(cls) -> QuerySet[ModelType]:
    #     """Get the unfiltered and unsorted QuerySet of all objects that this Actor might care about."""
    #     return cls.Model.objects.filter(extractor='favicon')
