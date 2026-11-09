"""Replay lookups must not duplicate a crawl's intake for every candidate."""

import sys
import threading
from datetime import timedelta

import django
import psutil
import pytest
import requests
from django.contrib.auth import get_user_model
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.core.routes_util import get_snapshot_host
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("route", ["original-domain", "owner-domain", "owner-date-domain"])
def test_replay_candidates_do_not_duplicate_crawl_intake(archivebox_daemon_server, route):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite", BASE_URL="http://archivebox.localhost")
    state = server.wait_for_workers(("worker_uvicorn",))
    worker = psutil.Process(state["worker_uvicorn"]["pid"])
    saved = b"The newest public capture, not the newer private capture.\n"
    with use_archivebox_db(server.data_dir):
        owner_user = get_user_model().objects.create_user(username="replay-memory-owner")
        crawl = Crawl.objects.create(urls="https://memory.example/", created_by=owner_user, status="sealed", retry_at=None)
        bookmarked_at = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # Different domains exercise the owner alias's Python-side filtering.
        # Original-domain replay still has 128 matching candidates to examine.
        snapshots = [
            Snapshot(
                crawl=crawl,
                url=f"https://{'memory.example' if index < 128 else 'other.example'}/item/{index}",
                timestamp=str(1700000000 + index),
                bookmarked_at=bookmarked_at + timedelta(seconds=index),
                status="sealed",
                retry_at=None,
                config={"PERMISSIONS": "public"},
            )
            for index in range(160)
        ]
        Snapshot.objects.bulk_create(snapshots)
        selected = snapshots[127]
        private = Snapshot.objects.create(
            crawl=crawl,
            url="https://memory.example/private",
            timestamp="1700001000",
            bookmarked_at=bookmarked_at + timedelta(seconds=1000),
            status="sealed",
            retry_at=None,
            config={"PERMISSIONS": "private"},
        )
        for snapshot, content in ((selected, saved), (private, b"Private capture must not be selected.\n")):
            payload = snapshot.output_dir / "responses" / "memory.example" / "probe.txt"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(content)
        owner = "web" if crawl.created_by.username == "system" else crawl.created_by.username
        snapshot_host = get_snapshot_host(str(selected.id), overrides={"BASE_URL": "http://archivebox.localhost"})
        replay_path = "/responses/memory.example/probe.txt"
        if route == "original-domain":
            path = "/original/memory.example/probe.txt"
            expected_location = f"http://{snapshot_host}{replay_path}"
        else:
            date_prefix = f"{bookmarked_at:%Y%m%d}/" if route == "owner-date-domain" else ""
            path = f"/{owner}/{date_prefix}memory.example"
            expected_location = f"/{selected.archive_path_from_db}"
        crawl_id = crawl.id

    base = f"http://127.0.0.1:{server.port}"
    with requests.Session() as client:
        client.trust_env = False
        # Warm imports, database connections, and the same query before changing
        # only the irrelevant intake text. The captured response stays tiny.
        for _ in range(2):
            response = client.get(base + path, headers={"Host": "web.archivebox.localhost"}, allow_redirects=False, timeout=30)
            assert response.status_code == 302, response.text
            assert response.headers["Location"] == expected_location
        replay = client.get(base + replay_path, headers={"Host": snapshot_host}, timeout=30)
        assert replay.status_code == 200
        assert replay.content == saved

        line = "https://intake.example/" + "a" * 40 + "\n"
        intake = line * (1024 * 1024 // len(line))
        with use_archivebox_db(server.data_dir):
            assert Crawl.objects.filter(pk=crawl_id).update(urls=intake) == 1

        baseline = worker.memory_info().rss
        samples = [baseline]
        stopped = threading.Event()

        def sample_rss():
            while not stopped.wait(0.005):
                samples.append(worker.memory_info().rss)

        sampler = threading.Thread(target=sample_rss)
        sampler.start()
        try:
            response = client.get(base + path, headers={"Host": "web.archivebox.localhost"}, allow_redirects=False, timeout=30)
            samples.append(worker.memory_info().rss)
        finally:
            stopped.set()
            sampler.join(timeout=5)
        assert not sampler.is_alive()
        assert response.status_code == 302, response.text
        assert response.headers["Location"] == expected_location
        growth = max(samples) - baseline
        print(f"{route}: Python={sys.version.split()[0]} Django={django.get_version()} intake={len(intake)} RSS growth={growth}")
        # 128-160 copies would exceed 128 MiB. Allow 32 MiB for normal request
        # work, while requiring replay to be independent of crawl intake size.
        assert growth < 32 * 1024 * 1024
        health = client.get(base + "/health/", timeout=5)
        assert health.status_code == 200
        assert health.content == b"OK"
