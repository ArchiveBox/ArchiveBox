"""Best-effort, snapshot-scoped hints for hooks. Never probe archive storage here."""

import json
from contextlib import ExitStack
from time import monotonic
from urllib.parse import urlsplit

from django.db import connections, transaction

from archivebox.config.constants import CONSTANTS
from archivebox.core.models import Snapshot


def cache_candidates(snapshot):
    result = []
    deadline = monotonic() + 0.1
    try:
        parsed = urlsplit(snapshot.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or len(snapshot.url) > 8192:
            return []
        alias = snapshot._state.db
        db = connections[alias]
        scoped = (
            Snapshot.objects.using(alias)
            .filter(
                status="sealed",
                crawl__created_by_id=snapshot.crawl.created_by_id,
                crawl__persona_id=snapshot.crawl.persona_id,
                permissions=snapshot.permissions,
            )
            .exclude(pk=snapshot.pk)
            .select_related("crawl__created_by")
            .only("url", "timestamp", "bookmarked_at", "created_at", "fs_version", "crawl__created_by__username")
            .order_by("-created_at", "-pk")
        )
        seen = set()
        size = 0
        with ExitStack() as stack, db.cursor() as cursor:
            if db.vendor == "sqlite":
                raw = db.connection
                busy = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
                cursor.execute("PRAGMA busy_timeout=0")
                stack.callback(raw.execute, f"PRAGMA busy_timeout={int(busy)}")
                stack.enter_context(transaction.atomic(using=alias))
                raw.set_progress_handler(lambda: int(monotonic() >= deadline), 500)
                stack.callback(raw.set_progress_handler, None, 0)
            elif db.vendor == "postgresql":
                stack.enter_context(transaction.atomic(using=alias))
            else:
                return []

            def collect(rows, limit):
                nonlocal size
                remaining = int((deadline - monotonic()) * 1000)
                if remaining < 1:
                    raise TimeoutError
                if db.vendor == "postgresql":
                    cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")
                for row in rows[:limit]:
                    if row.pk in seen or len(row.url) > 8192:
                        continue
                    path = row.get_storage_path_for_version(row.fs_version).relative_to(CONSTANTS.DATA_DIR)
                    if ".." in path.parts:
                        continue
                    hint = {"url": row.url, "snapdir": str(path), "created_at": row.created_at.isoformat()}
                    size += len(json.dumps(hint))
                    if size > 32000:
                        raise OverflowError
                    seen.add(row.pk)
                    result.append(hint)

            collect(scoped.filter(url=snapshot.url), 20)
            root = f"{parsed.scheme}://{parsed.netloc}"
            path = parsed.path.rstrip("/")
            if not (parsed.query or parsed.fragment):
                path = path.rpartition("/")[0]
            parents = []
            while len(parents) < 16:
                parents.append(root + path)
                if not path:
                    break
                path = path.rpartition("/")[0]
            for parent in parents:
                collect(scoped.filter(url__in=(parent, parent + "/")).exclude(url=snapshot.url), 1)
            for parent in parents:
                prefix = parent + "/"
                descendants = scoped.filter(url__startswith=prefix).exclude(url__in=(snapshot.url, prefix))
                if db.vendor == "sqlite":
                    # Binary range uses the normal URL index even with case-insensitive LIKE.
                    descendants = descendants.filter(url__gte=prefix, url__lt=parent + "0")
                collect(descendants, 1)
    except Exception:
        # A timeout, unavailable database or unusable historical row only drops hints.
        pass
    return result
