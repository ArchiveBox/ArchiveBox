#!/usr/bin/env python3
"""Benchmark ArchiveBox hot-path index queries at large row counts.

Run from inside an initialized (empty) collection directory, with the same
ARCHIVEBOX_DATABASE_* env vars the collection was initialized with:

    cd /path/to/collection
    uv run --project /path/to/ArchiveBox python /path/to/ArchiveBox/bin/benchmark_db_backends.py --rows 1000000

Seeds N snapshots (+1 archiveresult each) via bulk_create, runs ANALYZE, then
times the hot queries used by the admin UI, snapshot detail views, URL prefix
search, and the worker queue/claim paths. Works on both sqlite and postgres —
use it to compare backends or to catch performance regressions.
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone


def seed(rows: int, batch_size: int = 20_000) -> None:
    from django.db import transaction

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.uuid_compat import uuid7

    user_pk = get_or_create_system_user_pk()
    crawl = Crawl.objects.create(urls="https://example.com/", created_by_id=user_pk, status="sealed", label="benchmark seed")

    existing = Snapshot.objects.count()
    if existing >= rows:
        print(f"already seeded ({existing} snapshots)", flush=True)
        return

    base_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    started = time.monotonic()
    for start in range(existing, rows, batch_size):
        end = min(start + batch_size, rows)
        snapshots = []
        for i in range(start, end):
            created = base_time + timedelta(seconds=i)
            snapshots.append(
                Snapshot(
                    id=uuid7(),
                    url=f"https://site{i % 1000}.example.org/path/{i}" + ("#section" if i % 7 == 0 else ""),
                    timestamp=f"{1577836800 + i}.{i}",
                    title=f"Benchmark page {i}",
                    crawl=crawl,
                    bookmarked_at=created,
                    created_at=created,
                    modified_at=created,
                    downloaded_at=created if i % 10 else None,
                    status="sealed" if i % 20 else "queued",
                    retry_at=None if i % 20 else created,
                    fs_version="0.9.0",
                    config={},
                    depth=0,
                ),
            )
        with transaction.atomic():
            Snapshot.objects.bulk_create(snapshots, batch_size=batch_size)
            ArchiveResult.objects.bulk_create(
                [
                    ArchiveResult(
                        id=uuid7(),
                        snapshot=snapshot,
                        plugin="wget",
                        hook_name="on_Snapshot__06_wget.py",
                        status="succeeded",
                        created_at=snapshot.created_at,
                        modified_at=snapshot.created_at,
                        start_ts=snapshot.created_at,
                        end_ts=snapshot.created_at,
                        output_str="benchmark",
                        output_files={},
                    )
                    for snapshot in snapshots
                ],
                batch_size=batch_size,
            )
        if (end // batch_size) % 5 == 0 or end == rows:
            rate = (end - existing) / max(time.monotonic() - started, 0.001)
            print(f"  seeded {end}/{rows} snapshots ({rate:,.0f} rows/s)", flush=True)


def analyze_tables() -> None:
    from django.db import connection

    with connection.cursor() as cursor:
        for table in ("core_snapshot", "core_archiveresult"):
            cursor.execute(f"ANALYZE {table}")


def timed(func, repeat: int = 5) -> tuple[float, object]:
    times = []
    result = None
    for _ in range(repeat):
        started = time.perf_counter()
        result = func()
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times), result


def run_benchmarks(rows: int) -> dict[str, float]:
    from django.db import connection
    from django.db.models import Count, Q
    from django.utils import timezone as dj_timezone

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.misc.db import approximate_row_counts
    from archivebox.search.views import iter_url_prefix_search_ids

    now = dj_timezone.now()
    results: dict[str, float] = {}
    target_i = rows // 2
    target_url = f"https://site{target_i % 1000}.example.org/path/{target_i}"

    def fragmentless_q(url: str) -> Q:
        if connection.vendor == "sqlite":
            return Q(url=url) | (Q(url__gte=f"{url}#") & Q(url__lt=f"{url}#\U0010ffff"))
        return Q(url=url) | Q(url__startswith=f"{url}#")

    benchmarks = {
        "exact_count": lambda: Snapshot.objects.count(),
        "approximate_row_counts": lambda: approximate_row_counts(connection),
        "admin_list_page": lambda: list(Snapshot.objects.order_by("-bookmarked_at").values("id", "url", "title", "status", "bookmarked_at")[:40]),
        "admin_list_page_offset_10k": lambda: list(Snapshot.objects.order_by("-bookmarked_at").values("id", "url", "title")[10_000:10_040]),
        "snapshot_detail_by_url": lambda: list(Snapshot.objects.filter(fragmentless_q(target_url))[:10]),
        "snapshot_detail_archiveresults": lambda: list(
            ArchiveResult.objects.filter(snapshot__url=target_url).order_by("start_ts").values("id", "plugin", "status")[:100],
        ),
        "url_prefix_search": lambda: list(iter_url_prefix_search_ids("https://site500.example.org/", Snapshot.objects.all())),
        "worker_queue_scan": lambda: list(
            Snapshot.objects.filter(status="queued", retry_at__lte=now).order_by("retry_at", "created_at").values_list("id", flat=True)[:100],
        ),
        "status_facet_counts": lambda: dict(Snapshot.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")),
        "tag_join_filter": lambda: list(Snapshot.objects.filter(title__icontains="page 4242").values("id")[:20]),
    }

    for name, func in benchmarks.items():
        median_ms, _ = timed(func)
        results[name] = round(median_ms, 2)
        print(f"  {name:35s} {median_ms:10.2f} ms", flush=True)

    def claim_one() -> int:
        snapshot = Snapshot.objects.filter(status="queued").order_by("retry_at").first()
        if snapshot is None:
            return 0
        return Snapshot.objects.filter(pk=snapshot.pk, retry_at=snapshot.retry_at).update(retry_at=now + timedelta(seconds=60), modified_at=now)

    median_ms, _ = timed(claim_one)
    results["worker_cas_claim"] = round(median_ms, 2)
    print(f"  {'worker_cas_claim':35s} {median_ms:10.2f} ms", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--json", dest="json_path", default=None, help="also write results to this JSON file")
    args = parser.parse_args()

    from archivebox.config.django import setup_django
    from archivebox.misc.db import database_exists

    setup_django()
    assert database_exists(), "run archivebox init in this directory first"
    from django.db import connection

    print(f"backend: {connection.vendor}, target rows: {args.rows}", flush=True)
    print("seeding...", flush=True)
    seed(args.rows)
    if args.seed_only:
        return
    print("running ANALYZE...", flush=True)
    analyze_tables()
    print("benchmarks (median of 5):", flush=True)
    results = run_benchmarks(args.rows)
    results["_backend"] = connection.vendor
    results["_rows"] = args.rows
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
