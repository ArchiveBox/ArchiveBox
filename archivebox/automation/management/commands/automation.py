from django.core.management.base import BaseCommand

from archivebox.automation.service import run_pending_rules


class Command(BaseCommand):
    help = "Apply enabled automation rules to newly completed captures."

    def add_arguments(self, parser):
        parser.add_argument("--ai", action="store_true", help="Also process queued AI jobs until they finish.")

    def handle(self, **options):
        count = 0
        while processed := run_pending_rules():
            count += processed
        if options["ai"]:
            import time
            from archivebox.automation.ai import run_pending_enrichment

            while run_pending_enrichment():
                count += run_pending_rules()
                time.sleep(1)
            count += run_pending_rules()
        self.stdout.write(f"Processed {count} rule evaluations.")
