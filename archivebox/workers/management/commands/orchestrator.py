

from django.core.management.base import BaseCommand

from workers.orchestrator import ArchivingOrchestrator


class Command(BaseCommand):
    help = 'Run the archivebox orchestrator'

    # def add_arguments(self, parser):
    #     parser.add_argument('subcommand', type=str, help='The subcommand you want to run')
    #     parser.add_argument('command_args', nargs='*', help='Arguments to pass to the subcommand')


    def handle(self, *args, **kwargs):
        orchestrator = ArchivingOrchestrator()
        orchestrator.start()
