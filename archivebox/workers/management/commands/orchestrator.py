from django.core.management.base import BaseCommand

from workers.orchestrator import Orchestrator


class Command(BaseCommand):
    help = 'Run the archivebox orchestrator'

    def add_arguments(self, parser):
        parser.add_argument('--daemon', '-d', action='store_true', help="Run forever (don't exit on idle)")

    def handle(self, *args, **kwargs):
        daemon = kwargs.get('daemon', False)
        orchestrator = Orchestrator(exit_on_idle=not daemon)
        orchestrator.runloop()
