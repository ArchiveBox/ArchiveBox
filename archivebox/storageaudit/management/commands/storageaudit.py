import json
import os
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.machine.models import Process
from archivebox.storageaudit.service import audit_files, apply_cow, filter_groups, group_extensions, group_selection_hash, read_report


class Command(BaseCommand):
    help = "Audit real duplicate files across the collection, or apply explicitly selected native CoW groups."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, required=True)
        parser.add_argument("--process-id", default="")
        parser.add_argument("--source", default="")
        parser.add_argument("--group", action="append", default=[])
        parser.add_argument("--extension", default=None)
        parser.add_argument("--selection-hash", default="")
        parser.add_argument("--query", default="")

    def handle(self, *args, **options):
        if not get_user_model().objects.filter(pk=options["user"], is_active=True, is_superuser=True).exists():
            raise CommandError("A current superuser is required.")
        process = None
        if options["process_id"]:
            process = Process.objects.get(pk=options["process_id"], worker_type="storage-audit")
            if str(process.pk) not in process.cmd or process.cmd[:3] != [sys.executable, "-m", "archivebox"]:
                raise CommandError("Process does not belong to this command.")
        exit_code = 1
        try:
            if options["source"]:
                source = Process.objects.get(
                    pk=options["source"],
                    worker_type="storage-audit",
                    status=Process.StatusChoices.EXITED,
                    exit_code=0,
                )
                report = read_report(source)
                if options["extension"] is not None:
                    row = next(
                        (
                            item
                            for item in group_extensions(filter_groups(report.get("groups", []), options["query"]))
                            if item["extension"] == options["extension"]
                        ),
                        None,
                    )
                    if options["group"] or row is None or group_selection_hash(row["groups"]) != options["selection_hash"]:
                        raise CommandError("Extension selection changed; review the audit again.")
                    groups = row["groups"]
                else:
                    selected = set(options["group"])
                    groups = [group for group in report.get("groups", []) if group["id"] in selected]
                    if not selected or len(groups) != len(selected):
                        raise CommandError("Select existing groups from a completed audit.")
                if not report.get("complete"):
                    raise CommandError("Audit is incomplete.")
                result = apply_cow(groups)
                self.stdout.write(json.dumps({"complete": True, "operation": "copy-on-write", "result": result, "groups": len(groups)}))
            else:
                self.stdout.write(
                    json.dumps(
                        {"complete": False, "message": "Validating saved hash manifests and current file bytes across the collection."},
                    ),
                )
                self.stdout.flush()
                self.stdout.write(json.dumps(audit_files(Snapshot.objects.all())))
            exit_code = 0
        except ValueError as error:
            raise CommandError(str(error)) from error
        finally:
            if process:
                Process.objects.filter(pk=process.pk).update(
                    pid=os.getpid(),
                    status=Process.StatusChoices.EXITED,
                    exit_code=exit_code,
                    ended_at=timezone.now(),
                )
