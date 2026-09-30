import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Remove queued Snapshot files before deleting their database rows."

    def handle(self, *args, **kwargs):
        from archivebox.config import CONSTANTS
        from archivebox.core.models import Snapshot
        from archivebox.machine.models import Process

        current = Process.current()
        current.mark_running(
            process_type=Process.TypeChoices.WORKER,
            worker_type="worker_snapshot_delete",
            pwd=str(CONSTANTS.DATA_DIR),
        )
        while True:
            Snapshot.delete_requested(batch_size=100)
            current.heartbeat()
            time.sleep(60)
