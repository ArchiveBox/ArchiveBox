import os
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import resolve

from archivebox.config.common import get_config
from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot
from archivebox.linkhealth.service import check_snapshots
from archivebox.machine.models import Process


class Command(BaseCommand):
    help = "Check original snapshot URLs and add/remove their normal offline tag."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, required=True)
        parser.add_argument("--query", default="", help="Snapshot admin filter query string; empty scans all snapshots.")
        parser.add_argument("--snapshot", action="append", default=[])
        parser.add_argument("--before", default="")
        parser.add_argument("--process-id", default="")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(pk=options["user"], is_active=True, is_superuser=True).first()
        if user is None:
            raise CommandError("A current superuser is required.")
        request = RequestFactory().get("/admin/core/snapshot/?" + options["query"])
        request.resolver_match = resolve("/admin/core/snapshot/")
        request.user = user
        request.archivebox_config = get_config()
        snapshots = archivebox_admin._registry[Snapshot].get_list_queryset(request)
        if options["snapshot"]:
            snapshots = snapshots.filter(pk__in=options["snapshot"])
        if options["before"]:
            before = parse_datetime(options["before"])
            if before is None:
                raise CommandError("Invalid selection cutoff.")
            snapshots = snapshots.filter(created_at__lte=before)
        process = None
        if options["process_id"]:
            process = Process.objects.get(pk=options["process_id"], worker_type="link-check")
            if str(process.pk) not in process.cmd or process.cmd[:3] != [sys.executable, "-m", "archivebox"]:
                raise CommandError("Process does not belong to this command.")
        exit_code = 1
        try:
            check_snapshots(snapshots, self.stdout)
            exit_code = 0
        finally:
            if process:
                Process.objects.filter(pk=process.pk).update(
                    pid=os.getpid(),
                    status=Process.StatusChoices.EXITED,
                    exit_code=exit_code,
                    ended_at=timezone.now(),
                )
