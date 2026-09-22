import time

import psutil
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Stop a foreground-owned supervisord if its exact ArchiveBox owner Process exits."

    def add_arguments(self, parser):
        parser.add_argument("--supervisord-process-id", required=True)
        parser.add_argument("--interval", type=float, default=1.0)

    def handle(self, *args, **kwargs):
        from django.db import connections

        from archivebox.core.shutdown_util import wait_psutil_and_kill_children
        from archivebox.machine.models import Process

        supervisord_process_id = kwargs["supervisord_process_id"]
        interval = max(0.2, float(kwargs["interval"]))

        # This watchdog runs as a supervisord-managed helper outside the
        # orchestrator/runner. Keep every DB read/write as short as possible and
        # close Django's connection immediately so this process does not hold a
        # SQLite handle across sleep or process termination and trigger
        # "database is locked" failures in normal ArchiveBox work.
        def mark_supervisord_exited() -> None:
            try:
                supervisord_process.mark_exited(exit_code=0)
            finally:
                connections.close_all()

        while True:
            try:
                supervisord_process = Process.objects.select_related("parent").get(id=supervisord_process_id)
            except Process.DoesNotExist:
                return
            finally:
                connections.close_all()

            if supervisord_process.status != Process.StatusChoices.RUNNING:
                return

            owner = supervisord_process.parent
            if owner is not None and owner.status == Process.StatusChoices.RUNNING and owner.is_running:
                time.sleep(interval)
                continue

            try:
                supervisord = supervisord_process.proc
            finally:
                connections.close_all()
            if supervisord is None:
                mark_supervisord_exited()
                return

            try:
                children = supervisord.children(recursive=True)
                supervisord.terminate()
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                wait_psutil_and_kill_children(supervisord, children, timeout=5)
                mark_supervisord_exited()
            except psutil.NoSuchProcess:
                mark_supervisord_exited()
            except (BrokenPipeError, OSError, psutil.TimeoutExpired):
                pass
            return
