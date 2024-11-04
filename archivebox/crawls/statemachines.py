__package__ = 'archivebox.crawls'

from statemachine import State, StateMachine

from crawls.models import Crawl

# State Machine Definitions
#################################################


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
        return self.crawl.seed and self.crawl.seed.uri
        
    def is_finished(self) -> bool:
        return not self.crawl.has_pending_archiveresults()


        
    def on_started(self):
        self.crawl.create_root_snapshot()
        self.crawl.bump_retry_at(seconds=10)
        self.crawl.save()
        
    def on_sealed(self):
        self.crawl.retry_at = None
        self.crawl.save()
