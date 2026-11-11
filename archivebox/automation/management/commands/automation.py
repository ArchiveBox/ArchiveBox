from django.core.management.base import BaseCommand

from archivebox.automation.service import run_pending_rules


class Command(BaseCommand):
    help = "Apply enabled automation rules to newly completed captures."

    def handle(self, **options):
        count = 0
        while processed := run_pending_rules():
            count += processed
        self.stdout.write(f"Processed {count} rule evaluations.")
