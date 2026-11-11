"""Bounded, anonymous health probes and exact saved-content comparison."""

import atexit
import hashlib
import threading
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from django.db import IntegrityError, connections
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.machine.models import Process

from .models import LinkCheck, LinkHealthSettings, LinkScan


def normalized_url(url):
    """Ignore fragments and normalize authority; preserve query meaning and scheme."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and (parts.scheme.lower(), port) not in {("https", 443), ("http", 80)}:
            host += f":{port}"
        # Userinfo is intentionally preserved in candidate identity, but such
        # URLs are not probed by the anonymous checker.
        if "@" in parts.netloc:
            host = parts.netloc.rsplit("@", 1)[0] + "@" + host
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except (UnicodeError, ValueError):
        return url


def saved_content_hash(snapshot):
    """Hash one exact primary saved text/HTML file, bounded to 64 MiB.

    Files are selected from successful output manifests, never by walking the
    archive. Oversized/missing content stays unclassified rather than comparing
    prefixes or presenting a partial hash as proof of identity.
    """
    candidates = []
    for result in snapshot.archiveresult_set.filter(status="succeeded").only("id", "snapshot_id", "plugin", "output_files"):
        for relative, metadata in (result.output_files or {}).items():
            if not isinstance(metadata, dict) or metadata.get("mimetype", "").split(";")[0] not in {
                "text/plain",
                "text/html",
                "text/markdown",
            }:
                continue
            size = metadata.get("size", 0)
            if isinstance(size, int) and 0 < size <= 64 * 1024 * 1024:
                candidates.append((size, result, relative))
    for _, result, relative in sorted(candidates, key=lambda item: (-item[0], item[2])):
        base = Path(result.output_dir).resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base):
            continue
        try:
            if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
                continue
            digest = hashlib.sha256()
            total = 0
            with path.open("rb") as source:
                while chunk := source.read(65536):
                    total += len(chunk)
                    if total > 64 * 1024 * 1024:
                        break
                    digest.update(chunk)
            if 0 < total <= 64 * 1024 * 1024:
                return digest.hexdigest(), f"{result.plugin}/{relative}"
        except OSError:
            continue
    return "", ""


def check_snapshot(snapshot, session):
    url = snapshot.url
    values = {
        "checked_url": url,
        "normalized_url": normalized_url(url),
        "checked_at": timezone.now(),
        "status_code": None,
        "final_url": "",
        "message": "",
    }
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username is not None or parts.password is not None:
        values.update(status=LinkCheck.Status.UNSUPPORTED, message="Anonymous checks require an HTTP(S) URL without embedded credentials.")
    else:
        try:
            # GET is deliberate: many sites reject HEAD. Stream and close after
            # headers; checking availability never downloads a response body.
            with session.get(url, stream=True, timeout=(10, 20), allow_redirects=True) as response:
                code = response.status_code
                status = LinkCheck.Status.OTHER
                if 200 <= code < 300:
                    status = LinkCheck.Status.OK
                elif code in {404, 410}:
                    status = LinkCheck.Status.BROKEN
                elif code in {401, 403, 407, 429}:
                    status = LinkCheck.Status.RESTRICTED
                elif code >= 500:
                    status = LinkCheck.Status.TEMPORARY
                values.update(status=status, status_code=code, final_url=response.url)
        except requests.RequestException:
            values.update(
                status=LinkCheck.Status.UNREACHABLE,
                message="Connection, TLS, redirect or timeout failure. This does not establish that the link is gone.",
            )
    values["content_hash"], values["content_path"] = saved_content_hash(snapshot)
    LinkCheck.objects.update_or_create(snapshot=snapshot, defaults=values)


def enqueue(*, snapshot_ids=None):
    try:
        return LinkScan.objects.create(snapshot_ids=snapshot_ids or [])
    except IntegrityError:
        active = LinkScan.objects.filter(status__in=["queued", "running"]).first()
        if active is None:
            raise
        return active


def run_next(stop_event=None):
    scan = LinkScan.objects.filter(status="queued").order_by("created_at").first()
    if scan is None:
        return False
    if not LinkScan.objects.filter(pk=scan.pk, status="queued").update(
        status="running",
        started_at=timezone.now(),
        owner=Process.current(),
    ):
        return False
    try:
        snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED, created_at__lte=scan.created_at).order_by("pk")
        if scan.snapshot_ids:
            snapshots = snapshots.filter(pk__in=scan.snapshot_ids)
        LinkScan.objects.filter(pk=scan.pk).update(total=snapshots.count())
        with requests.Session() as session:
            # Do not load netrc credentials or carry browser Persona cookies into
            # probes. Restricted/authenticated pages remain a separate outcome.
            session.trust_env = False
            session.max_redirects = 10
            session.headers["User-Agent"] = "ArchiveBox link health checker"
            for snapshot in snapshots.iterator(chunk_size=100):
                if stop_event is not None and stop_event.is_set():
                    raise InterruptedError
                check_snapshot(snapshot, session)
                scan.checked += 1
                LinkScan.objects.filter(pk=scan.pk).update(checked=scan.checked)
        LinkScan.objects.filter(pk=scan.pk).update(
            status="succeeded",
            finished_at=timezone.now(),
            message="Anonymous availability checks finished. Captures were preserved.",
        )
    except InterruptedError:
        LinkScan.objects.filter(pk=scan.pk).update(
            status="interrupted",
            finished_at=timezone.now(),
            message="Worker stopped. Existing results remain; start another scan to continue.",
        )
    except Exception:
        LinkScan.objects.filter(pk=scan.pk).update(
            status="failed",
            finished_at=timezone.now(),
            message="Scan failed. Existing results remain; inspect worker logs before retrying.",
        )
        raise
    return True


def schedule_due():
    now = timezone.now()
    policy = LinkHealthSettings.objects.filter(pk=1, interval_days__gt=0, next_scan_at__lte=now).first()
    if policy:
        enqueue()
        LinkHealthSettings.objects.filter(pk=policy.pk, next_scan_at=policy.next_scan_at).update(
            next_scan_at=now + timedelta(days=policy.interval_days),
        )


def recover_interrupted():
    for scan in LinkScan.objects.filter(status="running").select_related("owner"):
        if scan.owner is None or not scan.owner.is_running:
            LinkScan.objects.filter(pk=scan.pk, status="running").update(
                status="interrupted",
                finished_at=timezone.now(),
                message="Worker stopped. Results already checked remain available.",
            )


_thread = None
_stop = threading.Event()


def _background():
    try:
        while not _stop.is_set():
            recover_interrupted()
            schedule_due()
            worked = run_next(_stop)
            connections.close_all()
            if not worked:
                _stop.wait(5)
    finally:
        connections.close_all()


def shutdown():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=1)


def tick(*, daemon):
    global _thread
    if not daemon:
        recover_interrupted()
        schedule_due()
        return run_next()
    if _thread is None or not _thread.is_alive():
        if _thread is None:
            atexit.register(shutdown)
        _stop.clear()
        _thread = threading.Thread(target=_background, name="archivebox-linkhealth", daemon=True)
        _thread.start()
    return False
