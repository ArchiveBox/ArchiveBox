__package__ = 'archivebox'

from django.core.management.base import BaseCommand


from .cli import run_subcommand


class Command(BaseCommand):
    help = 'Run an ArchiveBox CLI subcommand (e.g. add, remove, list, etc)'

    def add_arguments(self, parser):
        parser.add_argument('subcommand', type=str, help='The subcommand you want to run')
        parser.add_argument('command_args', nargs='*', help='Arguments to pass to the subcommand')


    def handle(self, *args, **kwargs):
        run_subcommand(kwargs['subcommand'], args=kwargs['command_args'])
