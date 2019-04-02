from django.core.management.base import BaseCommand


from legacy.archive import main


class Command(BaseCommand):
    help = 'ArchiveBox test.bee'

    def handle(self, *args, **kwargs):
        main(*args)
