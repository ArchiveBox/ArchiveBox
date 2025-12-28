__package__ = 'archivebox.crawls'

import os
from typing import ClassVar
from datetime import timedelta
from django.utils import timezone

from rich import print

from statemachine import State, StateMachine

# from workers.actor import ActorType
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
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(sealed, cond='is_finished')
    )
    
    def __init__(self, crawl, *args, **kwargs):
        self.crawl = crawl
        super().__init__(crawl, *args, **kwargs)
    
    def __repr__(self) -> str:
        return f'Crawl[{self.crawl.id}]'

    def __str__(self) -> str:
        return self.__repr__()
        
    def can_start(self) -> bool:
        if not self.crawl.urls:
            print(f'[red]⚠️ Crawl {self.crawl.id} cannot start: no URLs[/red]')
            return False
        urls_list = self.crawl.get_urls_list()
        if not urls_list:
            print(f'[red]⚠️ Crawl {self.crawl.id} cannot start: no valid URLs in urls field[/red]')
            return False
        return True
        
    def is_finished(self) -> bool:
        from core.models import Snapshot, ArchiveResult
        
        # check that at least one snapshot exists for this crawl
        snapshots = Snapshot.objects.filter(crawl=self.crawl)
        if not snapshots.exists():
            return False
        
        # check to make sure no snapshots are in non-final states
        if snapshots.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]).exists():
            return False
        
        # check that some archiveresults exist for this crawl
        results = ArchiveResult.objects.filter(snapshot__crawl=self.crawl)
        if not results.exists():
            return False
        
        # check if all archiveresults are finished
        if results.filter(status__in=[ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.STARTED]).exists():
            return False
        
        return True
        
    # def before_transition(self, event, state):
    #     print(f"Before '{event}', on the '{state.id}' state.")
    #     return "before_transition_return"

    @started.enter
    def enter_started(self):
        # Suppressed: state transition logs
        # Lock the crawl by bumping retry_at so other workers don't pick it up while we create snapshots
        self.crawl.update_for_workers(
            retry_at=timezone.now() + timedelta(seconds=30),  # Lock for 30 seconds
        )

        try:
            # Run the crawl - runs hooks, processes JSONL, creates snapshots
            self.crawl.run()

            # Update status to STARTED once snapshots are created
            self.crawl.update_for_workers(
                retry_at=timezone.now(),  # Process immediately
                status=Crawl.StatusChoices.STARTED,
            )
        except Exception as e:
            print(f'[red]⚠️ Crawl {self.crawl.id} failed to start: {e}[/red]')
            import traceback
            traceback.print_exc()
            # Re-raise so the worker knows it failed
            raise

    @sealed.enter
    def enter_sealed(self):
        # Clean up background hooks and run on_CrawlEnd hooks
        self.crawl.cleanup()

        # Suppressed: state transition logs
        self.crawl.update_for_workers(
            retry_at=None,
            status=Crawl.StatusChoices.SEALED,
        )
