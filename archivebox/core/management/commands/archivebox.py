__package__ = 'archivebox'

from django.core.management.base import BaseCommand

from archivebox.cli import main as run_cli


class Command(BaseCommand):
    help = 'Run an ArchiveBox CLI subcommand (e.g. add, remove, list, etc)'

    def add_arguments(self, parser):
        parser.add_argument('subcommand', type=str, help='The subcommand you want to run')
        parser.add_argument('command_args', nargs='*', help='Arguments to pass to the subcommand')


    def handle(self, *args, **kwargs):
        command_args = [kwargs['subcommand'], *kwargs['command_args']]
        run_cli(args=command_args)
