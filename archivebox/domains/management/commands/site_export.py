import os
from pathlib import Path
import json

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.domains.scope import crawl_site_scope, site_snapshot_filters
from archivebox.domains.export_service import FORMATS
from archivebox.domains.exports import export_snapshots_to_directory


class Command(BaseCommand):
    help = "Export a site's captured pages to a server directory."

    def add_arguments(self, parser):
        parser.add_argument("--crawl", default="")
        parser.add_argument("--scope", default="")
        parser.add_argument("--query", default=None)
        parser.add_argument("--user", default="")
        parser.add_argument("--public-only", action="store_true")
        parser.add_argument("--before", default="")
        parser.add_argument("--format", choices=FORMATS, required=True)
        parser.add_argument("--destination", required=True)
        parser.add_argument("--process-id", default="")
        parser.add_argument("--max-bytes", type=int, default=0)

    def handle(self, *args, **options):
        from django.conf import settings
        from archivebox.config.common import normalize_runtime_config
        from archivebox.core.exports import get_export_queryset, normalize_export_query
        from archivebox.plugins.discovery import plugin_operation

        try:
            if options["query"] is not None:
                if options["scope"] or options["crawl"]:
                    raise ValueError("Select a snapshot query or a domain scope, not both.")
                query = normalize_export_query(options["query"])
            else:
                crawl = Crawl.objects.get(pk=options["crawl"]) if options["crawl"] else None
                if not options["scope"] and crawl is None:
                    raise ValueError("Select --query FILTERS, --scope DOMAIN, or --crawl UUID.")
                query = site_snapshot_filters(options["scope"] or crawl_site_scope(crawl))
        except ValueError as error:
            raise CommandError(str(error)) from error
        user = None
        if options["user"]:
            user = get_user_model().objects.filter(pk=options["user"], is_active=True).first()
            if user is None or (not options["public_only"] and (not user.is_staff or not user.has_perm("core.view_snapshot"))):
                raise CommandError("The export user no longer has permission to view these snapshots.")
        title = query.get("domain") or "Snapshots"
        destination = Path(options["destination"])
        if not destination.is_absolute():
            raise CommandError("Export destination must be an absolute path.")
        process = Process.objects.get(pk=options["process_id"], worker_type="site-export") if options["process_id"] else None
        if process and (str(destination) not in process.cmd or str(process.pk) not in process.cmd):
            raise CommandError("Process does not belong to this export.")
        before = parse_datetime(options["before"]) if options["before"] else timezone.now()
        if before is None:
            raise CommandError("Invalid selection cutoff.")

        def progress(state):
            self.stdout.write(json.dumps(state))
            self.stdout.flush()

        code = 1
        try:
            identity = process or Process.current()
            attributes = {
                "process.id": str(identity.pk),
                "process.parent_id": str(identity.parent_id or ""),
                "process.type": identity.process_type,
                "worker.type": identity.worker_type,
            }
            if user is not None:
                attributes.update({"user.id": str(user.pk), "user.name": user.get_username()})
                if getattr(user, "email", None):
                    attributes["user.email"] = user.email
            with plugin_operation("site_export", normalize_runtime_config(settings.CONFIG), attributes=attributes):
                queryset = get_export_queryset(query, user=user, public_only=options["public_only"], selection_before=before)
                export_snapshots_to_directory(
                    queryset,
                    destination=destination,
                    format=options["format"],
                    max_bytes=options["max_bytes"],
                    title=title,
                    progress=progress,
                )
            code = 0
        except Exception as error:
            raise CommandError(str(error)) from error
        finally:
            if process:
                Process.objects.filter(pk=process.pk).update(
                    pid=os.getpid(),
                    status=Process.StatusChoices.EXITED,
                    exit_code=code,
                    ended_at=timezone.now(),
                )
