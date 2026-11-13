import os
from pathlib import Path
import json
import shutil
import zipfile

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from archivebox.config.common import get_config
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.misc.logging_util import printable_filesize
from archivebox.domains.scope import crawl_site_scope, normalize_site_scope, site_snapshots
from archivebox.domains.export_service import FORMATS
from archivebox.domains.exports import write_replay_site, write_static_site


class Command(BaseCommand):
    help = "Export a site's captured pages to a server directory."

    def add_arguments(self, parser):
        parser.add_argument("--crawl", default="")
        parser.add_argument("--scope", default="")
        parser.add_argument("--format", choices=FORMATS, required=True)
        parser.add_argument("--destination", required=True)
        parser.add_argument("--process-id", default="")
        parser.add_argument("--max-bytes", type=int, default=0)

    def handle(self, *args, **options):
        crawl = Crawl.objects.get(pk=options["crawl"]) if options["crawl"] else None
        if not options["scope"] and crawl is None:
            raise CommandError("Select a site with --scope DOMAIN or --crawl UUID.")
        try:
            scope = normalize_site_scope(options["scope"] or crawl_site_scope(crawl))
        except ValueError as error:
            raise CommandError(str(error)) from error
        destination = Path(options["destination"])
        if not destination.is_absolute():
            raise CommandError("Export destination must be an absolute path.")
        process = Process.objects.get(pk=options["process_id"], worker_type="site-export") if options["process_id"] else None
        if process and (str(destination) not in process.cmd or str(process.pk) not in process.cmd):
            raise CommandError("Process does not belong to this export.")
        state = {"destination": str(destination), "format": options["format"], "bytes": 0}

        def progress(update):
            limit = options["max_bytes"]
            if limit and max(update.get("bytes", 0), update.get("total_bytes", 0)) > limit:
                raise ValueError(f"Export exceeds the {printable_filesize(limit)} ({limit} bytes) limit.")
            state.update(update)
            self.stdout.write(json.dumps(state))
            self.stdout.flush()

        code = 1
        try:
            destination.mkdir(parents=True, exist_ok=False)
            progress({})
            # Materialize before filesystem I/O, with no long SQLite reader.
            queryset = site_snapshots(scope).filter(created_at__lte=timezone.now())

            def snapshots():
                after = None
                while True:
                    selected = queryset
                    if after:
                        selected = selected.filter(Q(created_at__lt=after[0]) | Q(created_at=after[0], pk__lt=after[1]))
                    batch = list(selected.order_by("-created_at", "-pk").prefetch_related("archiveresult_set")[:100])
                    if not batch:
                        return
                    after = (batch[-1].created_at, batch[-1].pk)
                    yield from batch

            if options["format"] in {"html", "html_zip"}:
                write_static_site(destination, snapshots(), title=scope, progress=progress, max_bytes=options["max_bytes"])
            else:
                write_replay_site(
                    destination,
                    snapshots(),
                    title=scope,
                    config=get_config(),
                    progress=progress,
                    player=options["format"] == "replay",
                )
            if options["format"] == "html_zip":
                with zipfile.ZipFile(destination / "site.zip", "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
                    for item in destination.rglob("*"):
                        if item.is_file() and item.name != "site.zip":
                            bundle.write(item, item.relative_to(destination).as_posix())
                if options["max_bytes"] and (destination / "site.zip").stat().st_size > options["max_bytes"]:
                    (destination / "site.zip").unlink()
                    raise ValueError(
                        f"Export ZIP exceeds the {printable_filesize(options['max_bytes'])} ({options['max_bytes']} bytes) limit.",
                    )
                for item in destination.iterdir():
                    if item.name != "site.zip":
                        shutil.rmtree(item) if item.is_dir() else item.unlink()
            archive_file = destination / ("site.zip" if options["format"] == "html_zip" else "site.wacz")
            if archive_file.is_file() and options["max_bytes"] and archive_file.stat().st_size > options["max_bytes"]:
                archive_file.unlink()
                raise ValueError(
                    f"Export archive exceeds the {printable_filesize(options['max_bytes'])} ({options['max_bytes']} bytes) limit.",
                )
            progress({"complete": True, **({"bytes": archive_file.stat().st_size} if archive_file.is_file() else {})})
            code = 0
        except Exception as error:
            progress({"error": str(error), "complete": False})
            raise CommandError(str(error)) from error
        finally:
            if process:
                Process.objects.filter(pk=process.pk).update(
                    pid=os.getpid(),
                    status=Process.StatusChoices.EXITED,
                    exit_code=code,
                    ended_at=timezone.now(),
                )
