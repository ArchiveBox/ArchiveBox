from django.core.management.base import BaseCommand

from archivebox.workers.orchestrator import Orchestrator


class Command(BaseCommand):
    help = 'Run the archivebox orchestrator'

    def add_arguments(self, parser):
        parser.add_argument(
            '--exit-on-idle',
            action='store_true',
            default=False,
            help="Exit when all work is complete (default: run forever)"
        )

    def handle(self, *args, **kwargs):
        exit_on_idle = kwargs.get('exit_on_idle', False)
        orchestrator = Orchestrator(exit_on_idle=exit_on_idle)
        orchestrator.runloop()
