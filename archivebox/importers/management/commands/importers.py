from django.core.management.base import BaseCommand, CommandError

from archivebox.importers.models import ImporterSource
from archivebox.importers.service import enqueue, enqueue_due, recover_interrupted, run_next_importer


class Command(BaseCommand):
    help = "Run queued plugin importers, or enqueue an action for a configured source."

    def add_arguments(self, parser):
        parser.add_argument("--source", help="Configured importer source UUID")
        parser.add_argument("--action", choices=["check", "preview", "import"], default="import")
        parser.add_argument("--due", action="store_true", help="Also enqueue due schedules")
        parser.add_argument("--once", action="store_true", help="Process at most one queued run")

    def handle(self, *args, **options):
        recover_interrupted()
        if options["source"]:
            try:
                enqueue(ImporterSource.objects.get(pk=options["source"]), options["action"])
            except (ImporterSource.DoesNotExist, ValueError) as error:
                raise CommandError(str(error)) from error
        if options["due"]:
            enqueue_due()
        count = 0
        while run_next_importer():
            count += 1
            if options["once"]:
                break
        self.stdout.write(f"Processed {count} importer runs. Inspect /admin/importers/ for results.")
