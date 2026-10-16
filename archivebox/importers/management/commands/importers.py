from django.core.management.base import BaseCommand, CommandError

from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.importers.service import enqueue, enqueue_due, recover_interrupted, run_next_importer


class Command(BaseCommand):
    help = "Run queued plugin importers, or enqueue an action for a configured source."

    def add_arguments(self, parser):
        parser.add_argument("--source", help="Run only this configured importer source UUID")
        parser.add_argument("--action", choices=ImporterRun.Action.values, default="import")
        parser.add_argument("--due", action="store_true", help="Also enqueue due schedules")
        parser.add_argument("--once", action="store_true", help="Process at most one queued run")

    def handle(self, *args, **options):
        recover_interrupted()
        source = None
        if options["source"]:
            try:
                source = ImporterSource.objects.get(pk=options["source"])
                enqueue(source, options["action"])
            except (ImporterSource.DoesNotExist, ValueError) as error:
                raise CommandError(str(error)) from error
        if options["due"]:
            enqueue_due()
        count = 0
        failures = []
        while True:
            queued = ImporterRun.objects.filter(status=ImporterRun.Status.QUEUED)
            if source is not None:
                queued = queued.filter(source=source)
            run = queued.order_by("created_at").only("id").first()
            if run is None or not run_next_importer(run_id=run.pk):
                break
            count += 1
            run.refresh_from_db(fields=["status"])
            if run.status != ImporterRun.Status.SUCCEEDED:
                failures.append(f"{run.pk}: {run.status}")
            if options["once"]:
                break
        self.stdout.write(f"Processed {count} importer runs. Inspect /admin/importers/ for results.")
        if failures:
            raise CommandError(f"Importer runs did not succeed: {', '.join(failures)}. Inspect /admin/importers/ for details.")
