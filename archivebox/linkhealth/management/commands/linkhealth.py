from django.core.management.base import BaseCommand

from archivebox.linkhealth.service import enqueue, recover_interrupted, run_next, schedule_due


class Command(BaseCommand):
    help = "Check original URL availability and compare saved content without deleting captures."

    def add_arguments(self, parser):
        parser.add_argument("--scan", action="store_true", help="Queue a new scan before processing.")
        parser.add_argument("--once", action="store_true", help="Process at most one queued scan.")

    def handle(self, *args, **options):
        recover_interrupted()
        schedule_due()
        if options["scan"]:
            scan = enqueue()
            self.stdout.write(f"Queued link scan {scan.pk}")
        while run_next():
            if options["once"]:
                break
