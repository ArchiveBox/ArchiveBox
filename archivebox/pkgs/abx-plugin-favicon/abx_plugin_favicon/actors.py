__package__ = 'abx_plugin_favicon'

from typing import ClassVar

from core.actors import ActorType
from core.statemachines import ArchiveResultMachine

from statemachine import State

from .models import FaviconResult


class FaviconResultActor(ActorType[FaviconResult]):
    """
    The primary actor for progressing ArchiveResult objects
    through their lifecycle using the ArchiveResultMachine.
    """
    Model = FaviconResult
    StateMachineClass = ArchiveResultMachine
    
    ACTIVE_STATE: ClassVar[State] = ArchiveResultMachine.started                # 'started'
    FINAL_STATES: ClassVar[list[State]] = ArchiveResultMachine.final_states     # ['succeeded', 'failed', 'skipped']
    STATE_FIELD_NAME: ClassVar[str] = ArchiveResultMachine.state_field_name     # status
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 6
    MAX_TICK_TIME: ClassVar[int] = 60
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10

    # @classproperty
    # def qs(cls) -> QuerySet[ModelType]:
    #     """Get the unfiltered and unsorted QuerySet of all objects that this Actor might care about."""
    #     return cls.Model.objects.filter(extractor='favicon')
