__package__ = 'archivebox.crawls'

from typing import ClassVar
from django.utils import timezone

from statemachine import State, StateMachine

from actors.actor import ActorType
from crawls.models import Crawl


class CrawlMachine(StateMachine, strict_states=True):
    """State machine for managing Crawl lifecycle."""
    
    model: Crawl
    
    # States
    queued = State(value=Crawl.StatusChoices.QUEUED, initial=True)
    started = State(value=Crawl.StatusChoices.STARTED)
    sealed = State(value=Crawl.StatusChoices.SEALED, final=True)
    
    # Tick Event
    tick = (
        queued.to.itself(unless='can_start', internal=True) |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished', internal=True) |
        started.to(sealed, cond='is_finished')
    )
    
    def __init__(self, crawl, *args, **kwargs):
        self.crawl = crawl
        super().__init__(crawl, *args, **kwargs)
        
    def can_start(self) -> bool:
        return bool(self.crawl.seed and self.crawl.seed.uri and (self.retry_at < timezone.now()))
        
    def is_finished(self) -> bool:
        if not self.crawl.snapshot_set.exists():
            return False
        if self.crawl.pending_snapshots().exists():
            return False
        if self.crawl.pending_archiveresults().exists():
            return False
        return True
        
    # def before_transition(self, event, state):
    #     print(f"Before '{event}', on the '{state.id}' state.")
    #     return "before_transition_return"

    @started.enter
    def enter_started(self):
        print(f'CrawlMachine[{self.crawl.ABID}].on_started(): crawl.create_root_snapshot() + crawl.bump_retry_at(+10s)')
        self.crawl.status = Crawl.StatusChoices.STARTED
        self.crawl.bump_retry_at(seconds=2)
        self.crawl.save()
        self.crawl.create_root_snapshot()

    @sealed.enter        
    def enter_sealed(self):
        print(f'CrawlMachine[{self.crawl.ABID}].on_sealed(): crawl.retry_at=None')
        self.crawl.status = Crawl.StatusChoices.SEALED
        self.crawl.retry_at = None
        self.crawl.save()


class CrawlWorker(ActorType[Crawl]):
    """The Actor that manages the lifecycle of all Crawl objects"""
    
    Model = Crawl
    StateMachineClass = CrawlMachine
    
    ACTIVE_STATE: ClassVar[State] = CrawlMachine.started
    FINAL_STATES: ClassVar[list[State]] = CrawlMachine.final_states
    STATE_FIELD_NAME: ClassVar[str] = Crawl.state_field_name
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 3
    MAX_TICK_TIME: ClassVar[int] = 10
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10

