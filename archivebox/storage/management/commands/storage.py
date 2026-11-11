from django.core.management.base import BaseCommand, CommandError

from archivebox.storage.models import StorageRun
from archivebox.storage.service import recover_interrupted, run_next


class Command(BaseCommand):
    help = "Process queued storage connection checks and archive copies."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        recover_interrupted()
        while run := StorageRun.objects.filter(status="queued").order_by("created_at").first():
            if not run_next(run_id=run.pk):
                break
            run.refresh_from_db()
            self.stdout.write(f"{run.pk}: {run.status}: {run.message}")
            if run.status != StorageRun.Status.SUCCEEDED:
                raise CommandError("Storage operation did not succeed.")
            if options["once"]:
                break
