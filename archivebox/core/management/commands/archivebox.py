from django.core.management.base import BaseCommand


from core.archive import main

class Command(BaseCommand):
    help = 'ArchiveBox test.bee'

    def handle(self, *args, **kwargs):
        main()
