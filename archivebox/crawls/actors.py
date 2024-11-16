__package__ = 'archivebox.crawls'

from typing import ClassVar

from crawls.models import Crawl
from crawls.statemachines import CrawlMachine

from actors.actor import ActorType, State


class CrawlActor(ActorType[Crawl]):
    """The Actor that manages the lifecycle of all Crawl objects"""
    
    Model = Crawl
    StateMachineClass = CrawlMachine
    
    ACTIVE_STATE: ClassVar[State] = CrawlMachine.started
    FINAL_STATES: ClassVar[list[State]] = CrawlMachine.final_states
    STATE_FIELD_NAME: ClassVar[str] = Crawl.state_field_name
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = 1
    MAX_TICK_TIME: ClassVar[int] = 10
    CLAIM_FROM_TOP_N: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10
