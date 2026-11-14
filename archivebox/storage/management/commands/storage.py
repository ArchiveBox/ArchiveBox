import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from archivebox.machine.models import Process
from archivebox.storage import service


class Command(BaseCommand):
    help = "Install, verify, or activate rclone as primary archive storage."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["install", "check", "activate", "reconnect"])
        parser.add_argument("--revision", default="")

    def handle(self, *args, **options):
        # FUSE uses the real UID for mount ownership. ArchiveBox can retain a
        # real root UID while running as the app's effective UID; permanently
        # drop it in this dedicated subprocess so the app can access its mount.
        if os.getgid() != os.getegid():
            os.setregid(os.getegid(), os.getegid())
        if os.getuid() != os.geteuid():
            os.setreuid(os.geteuid(), os.geteuid())
        for key in list(os.environ):
            if key.startswith("RCLONE_"):
                del os.environ[key]
        process = Process.current()
        process.worker_type = "storage"
        process.save(update_fields=["worker_type"])
        action = options["action"]
        revision = options["revision"] or service.settings().get("ARCHIVE_STORAGE_REVISION", "")
        try:
            if action == "install":
                service.managed_binary(install=True)
                message = "rclone installed. FUSE must be enabled on the server before activation."
            elif action == "check":
                service.check_connection(revision)
                message = "Connection verified: wrote, read back, and removed a temporary file."
            elif action == "activate":
                service.activate(revision)
                message = "Primary archive storage active. Original archive preserved; new captures and replay use the mount."
            else:
                with service.archive_access(exclusive=True):
                    service.reconnect(revision)
                message = "Primary archive mount reconnected."
        except Exception as error:
            process.exit_code = 1
            process.stderr = str(error)
            raise CommandError(str(error)) from error
        else:
            process.exit_code = 0
            process.stdout = message
            self.stdout.write(message)
        finally:
            process.status = "exited"
            process.ended_at = timezone.now()
            process.save(update_fields=["status", "exit_code", "stdout", "stderr", "ended_at"])
