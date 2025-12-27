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
        if results.filter(status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED]).exists():
            return False
        
        return True
        
    # def before_transition(self, event, state):
    #     print(f"Before '{event}', on the '{state.id}' state.")
    #     return "before_transition_return"

    @started.enter
    def enter_started(self):
        # Suppressed: state transition logs
        # lock the crawl object while we create snapshots
        self.crawl.update_for_workers(
            retry_at=timezone.now(),  # Process immediately
            status=Crawl.StatusChoices.QUEUED,
        )

        try:
            # Run on_Crawl hooks to validate/install dependencies
            self._run_crawl_hooks()

            # Run the crawl - creates root snapshot and processes queued URLs
            self.crawl.run()

            # only update status to STARTED once snapshots are created
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

    def _run_crawl_hooks(self):
        """Run on_Crawl hooks to validate/install dependencies."""
        from pathlib import Path
        from archivebox.hooks import run_hooks, discover_hooks
        from archivebox.config import CONSTANTS

        # Discover and run all on_Crawl hooks
        hooks = discover_hooks('Crawl')
        if not hooks:
            return

        # Create a temporary output directory for hook results
        output_dir = Path(CONSTANTS.DATA_DIR) / 'tmp' / f'crawl_{self.crawl.id}'
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run all on_Crawl hooks
        first_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ''
        results = run_hooks(
            event_name='Crawl',
            output_dir=output_dir,
            timeout=60,
            config_objects=[self.crawl],
            crawl_id=str(self.crawl.id),
            source_url=first_url,
        )

        # Process hook results - parse JSONL output and create DB objects
        self._process_hook_results(results)

    def _process_hook_results(self, results: list):
        """Process JSONL output from hooks to create InstalledBinary and update Machine config."""
        import json
        from machine.models import Machine, InstalledBinary

        machine = Machine.current()

        for result in results:
            if result['returncode'] != 0:
                # Hook failed - might indicate missing dependency
                continue

            # Parse JSONL output
            for line in result['stdout'].strip().split('\n'):
                if not line.strip():
                    continue

                try:
                    obj = json.loads(line)
                    obj_type = obj.get('type')

                    if obj_type == 'InstalledBinary':
                        # Create or update InstalledBinary record
                        # Skip if essential fields are missing
                        if not obj.get('name') or not obj.get('abspath') or not obj.get('version'):
                            continue

                        InstalledBinary.objects.update_or_create(
                            machine=machine,
                            name=obj['name'],
                            defaults={
                                'abspath': obj['abspath'],
                                'version': obj['version'],
                                'sha256': obj.get('sha256') or '',
                                'binprovider': obj.get('binprovider') or 'env',
                            }
                        )

                    elif obj_type == 'Machine':
                        # Update Machine config
                        method = obj.get('_method', 'update')
                        if method == 'update':
                            key = obj.get('key', '')
                            value = obj.get('value')
                            if key.startswith('config/'):
                                config_key = key[7:]  # Remove 'config/' prefix
                                machine.config[config_key] = value
                                machine.save(update_fields=['config'])

                    elif obj_type == 'Dependency':
                        # Create Dependency record from JSONL
                        from machine.models import Dependency

                        bin_name = obj.get('bin_name')
                        if not bin_name:
                            continue

                        # Create or get existing dependency
                        dependency, created = Dependency.objects.get_or_create(
                            bin_name=bin_name,
                            defaults={
                                'bin_providers': obj.get('bin_providers', '*'),
                                'overrides': obj.get('overrides', {}),
                                'config': obj.get('config', {}),
                            }
                        )

                        # Run dependency installation if not already installed
                        if not dependency.is_installed:
                            dependency.run()

                except json.JSONDecodeError:
                    # Not JSON, skip
                    continue

    @sealed.enter
    def enter_sealed(self):
        # Run on_CrawlEnd hooks to clean up resources (e.g., kill shared Chrome)
        self._run_crawl_end_hooks()

        # Suppressed: state transition logs
        self.crawl.update_for_workers(
            retry_at=None,
            status=Crawl.StatusChoices.SEALED,
        )

    def _run_crawl_end_hooks(self):
        """Run on_CrawlEnd hooks to clean up resources at crawl completion."""
        from pathlib import Path
        from archivebox.hooks import run_hooks, discover_hooks
        from archivebox.config import CONSTANTS

        # Discover and run all on_CrawlEnd hooks
        hooks = discover_hooks('CrawlEnd')
        if not hooks:
            return

        # Use the same temporary output directory from crawl start
        output_dir = Path(CONSTANTS.DATA_DIR) / 'tmp' / f'crawl_{self.crawl.id}'

        # Run all on_CrawlEnd hooks
        first_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ''
        results = run_hooks(
            event_name='CrawlEnd',
            output_dir=output_dir,
            timeout=30,  # Cleanup hooks should be quick
            config_objects=[self.crawl],
            crawl_id=str(self.crawl.id),
            source_url=first_url,
        )

        # Log any failures but don't block sealing
        for result in results:
            if result['returncode'] != 0:
                print(f'[yellow]⚠️ CrawlEnd hook failed: {result.get("hook", "unknown")}[/yellow]')
                if result.get('stderr'):
                    print(f'[dim]{result["stderr"][:200]}[/dim]')
