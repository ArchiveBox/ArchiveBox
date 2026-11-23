"""Run the query interpreter through registered plugin executables and real snapshot storage."""

import json
import os
import subprocess
from uuid import UUID

import pytest
from abx_plugins import get_plugins_dir

from archivebox.config.common import get_config
from archivebox.config.constants import CONSTANTS
from archivebox.core.models import Snapshot
from archivebox.search.interpreter import SnapshotSearch

pytestmark = pytest.mark.django_db


def output(snapshot, path, text):
    dest = snapshot.output_dir / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def run_hook(snapshot, plugin, *args, **config):
    (hook,) = (get_plugins_dir() / plugin).glob("on_Snapshot__*.py")
    dest = snapshot.output_dir / plugin
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(hook), "--url", snapshot.url, *args],
        cwd=dest,
        env={**os.environ, "DATA_DIR": str(CONSTANTS.DATA_DIR), "SNAP_DIR": str(snapshot.output_dir), **config},
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert any(record.get("status") == "succeeded" for record in records), result.stdout


def test_link_operators_follow_real_outlinks_in_both_directions_within_scope(crawl):
    source = Snapshot.objects.create(crawl=crawl, url="https://archive.example/reader")
    destination = Snapshot.objects.create(crawl=crawl, url="https://papers.example/ABC")
    private = Snapshot.objects.create(crawl=crawl, url="https://private.example/paper")
    output(source, "dom/output.html", f'<a href="{destination.url}">Read</a><a href="{private.url}">Draft</a>')
    run_hook(source, "parse_html_urls")

    scope = Snapshot.objects.filter(pk__in=[source.pk, destination.pk])
    assert list(SnapshotSearch(scope, 'linksto:"papers.example/ABC"').stream()) == [source.pk]
    assert list(SnapshotSearch(scope, 'linksto:"papers.example/abC"').stream()) == []
    assert list(SnapshotSearch(scope, "linkedfrom:archive.example").stream()) == [destination.pk]
    assert list(SnapshotSearch(scope.exclude(pk=source.pk), "linkedfrom:archive.example").stream()) == []


def test_search_and_recursive_crawl_share_saved_plugin_urls(crawl):
    from archivebox.plugins.hooks import collect_urls_from_plugins

    source = Snapshot.objects.create(crawl=crawl, url="https://news.example/story")
    target = Snapshot.objects.create(crawl=crawl, url="https://article.example/paper")
    # An old/custom parser need no longer be installed. Recursive discovery
    # also accepts plain URL lines and strips dangling prose punctuation.
    output(source, "retired_parser/urls.jsonl", target.url + ",\n")
    records = collect_urls_from_plugins(source.output_dir)
    assert [(row["plugin"], row["url"]) for row in records] == [("retired_parser", target.url)]
    scope = Snapshot.objects.filter(pk__in=[source.pk, target.pk])
    for streaming in (False, True):
        assert list(SnapshotSearch(scope, "linkedfrom:news.example", streaming=streaming).stream()) == [target.pk]
        assert list(SnapshotSearch(scope, "linksto:article.example", streaming=streaming).stream()) == [source.pk]


def test_links_in_pre_migration_output_directory(crawl):
    source = Snapshot.objects.create(crawl=crawl, url="https://legacy.example/", fs_version="0.9.0")
    target = Snapshot.objects.create(crawl=crawl, url="https://already-archived.example/")
    standard = source.get_storage_path_for_version(source.fs_version)
    legacy = standard.with_name(str(UUID(str(source.pk))))
    folder = legacy / "custom_parser"
    folder.mkdir(parents=True)
    (folder / "urls.jsonl").write_text(target.url)
    assert source.output_dir == legacy
    assert list(SnapshotSearch(Snapshot.objects.all(), "linkedfrom:legacy.example").stream()) == [target.pk]


def test_quoted_and_unquoted_link_values_match_the_same_substring(crawl):
    page = "https://news.ycombinator.com/some/specific/page"
    first, other = (Snapshot.objects.create(crawl=crawl, url=url) for url in (page, page + "/other"))
    # Cover both saved output and the database edge kept by recursive capture.
    target = Snapshot.objects.create(crawl=crawl, url="https://articles.example/a")
    child = Snapshot.objects.create(crawl=crawl, url=target.url + "/part", parent_snapshot=other)
    output(first, "parser/urls.jsonl", target.url)
    output(other, "parser/urls.jsonl", child.url)
    scope = Snapshot.objects.all()
    assert set(SnapshotSearch(scope, "linkedfrom:ycombinator.com").stream()) == {target.pk, child.pk}
    for field, value, expected in (("linkedfrom", page, {target.pk, child.pk}), ("linksto", target.url, {first.pk, other.pk})):
        for operand in (value, json.dumps(value)):
            assert set(SnapshotSearch(scope, f"{field}:{operand}").stream()) == expected


def test_recorded_crawl_edges_are_positive_link_evidence_without_files(crawl):
    parent = Snapshot.objects.create(crawl=crawl, url="https://news.example.org/story")
    child = Snapshot.objects.create(crawl=crawl, url="https://article.example/paper", parent_snapshot=parent)
    scope = Snapshot.objects.all()
    assert list(SnapshotSearch(scope, "linkedfrom:example.org").stream()) == [child.pk]
    assert list(SnapshotSearch(scope, "linksto:article.example").stream()) == [parent.pk]
    assert list(SnapshotSearch(scope, "linkedfrom:example.org AND domain:article.example").stream()) == [child.pk]
    assert not list(SnapshotSearch(scope.exclude(pk=parent.pk), "linkedfrom:example.org").stream())


def test_deep_shares_reads_after_metadata_filter_and_preserves_unknown_under_negation(crawl):
    first = Snapshot.objects.create(crawl=crawl, url="https://reports.example/one")
    capped = Snapshot.objects.create(crawl=crawl, url="https://reports.example/two")
    outside = Snapshot.objects.create(crawl=crawl, url="https://unrelated.example/")
    output(first, "dom/output.html", "Orbit Alpha:Beta")
    output(capped, "dom/output.html", "x" * (512 * 1024) + "Orbit Alpha:Beta")
    output(outside, "dom/output.html", "Orbit Alpha:Beta")
    config = get_config(overrides={"SEARCH_BACKEND_ENGINE": "ripgrep"})
    scope = Snapshot.objects.filter(pk__in=[first.pk, capped.pk, outside.pk])
    search = SnapshotSearch(scope, 'domain:reports.example (deep:"Orbit" AND deep:"Alpha:Beta")', config=config)
    assert list(search.stream()) == [first.pk]
    assert search.partial
    assert search.usage["bytes"] == len("Orbit Alpha:Beta") + 512 * 1024
    assert search.usage["files"] == 2
    negative = SnapshotSearch(scope, 'domain:reports.example ~deep:"Heavy"', config=config)
    assert list(negative.stream()) == [first.pk]
    assert negative.partial


def test_sqlite_native_rank_explicit_sort_and_quoted_colons(crawl):
    weak = Snapshot.objects.create(id=UUID(int=1), crawl=crawl, url="https://papers.example/a", title="A")
    strong = Snapshot.objects.create(id=UUID(int=2), crawl=crawl, url="https://papers.example/b", title="B")
    unindexed = Snapshot.objects.create(id=UUID(int=3), crawl=crawl, url="https://papers.example/c", title="C")
    for snapshot, article in [
        (weak, "galaxy and " + "many details " * 90),
        (strong, "galaxy galaxy galaxy ABC:DEF"),
    ]:
        output(snapshot, "readability/article.txt", article)
        run_hook(snapshot, "search_backend_sqlite", "--snapshot-id", str(snapshot.pk), SEARCH_BACKEND_SQLITE_ENABLED="true")
    config = get_config(overrides={"SEARCH_BACKEND_ENGINE": "sqlite"})
    scope = Snapshot.objects.filter(pk__in=[weak.pk, strong.pk, unindexed.pk])
    positive = SnapshotSearch(scope, "domain:papers.example galaxy", config=config)
    assert list(positive.stream()) == [strong.pk, weak.pk]
    assert list(SnapshotSearch(scope, "galaxy", config=config).stream()) == [strong.pk, weak.pk]
    assert list(SnapshotSearch(scope.order_by("title"), "domain:papers.example galaxy", config=config).stream()) == [weak.pk, strong.pk]
    assert list(SnapshotSearch(scope, '"ABC:DEF"', config=config).stream()) == [strong.pk]
    assert list(SnapshotSearch(scope, '~"ABC:DEF"', config=config).stream()) == [weak.pk]

    # The index returns its confirmed ranked hits without waiting for a broad
    # metadata scan; a row with only metadata must still arrive exactly once.
    unindexed.title = "galaxy"
    unindexed.save(update_fields=["title"])
    assert list(SnapshotSearch(scope, "galaxy", config=config).stream()) == [strong.pk, weak.pk, unindexed.pk]
    for query in ("domain:papers.example galaxy", "(galaxy OR title:galaxy) AND domain:papers.example"):
        hits = list(SnapshotSearch(scope, query, config=config).stream())
        assert sorted(hits) == [weak.pk, strong.pk, unindexed.pk]
    assert list(SnapshotSearch(scope.order_by("pk"), "domain:papers.example galaxy", config=config).stream()) == [
        weak.pk,
        strong.pk,
        unindexed.pk,
    ]


@pytest.mark.django_db(transaction=True)
def test_stream_resumes_metadata_windows_after_a_full_first_page(crawl):
    # The first window has no matches. The next one exceeds a page; SQL
    # must resume after it without dropping its tail or emitting it twice.
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                id=UUID(int=i + 1),
                crawl=crawl,
                url=f"https://reports.example/{i}",
                timestamp=str(1802000000 + i),
                title="research" if 70 <= i <= 345 else "other",
            )
            for i in range(350)
        ],
    )
    indexed = rows[-1]
    output(indexed, "readability/article.txt", "planetary")
    run_hook(indexed, "search_backend_sqlite", "--snapshot-id", str(indexed.pk), SEARCH_BACKEND_SQLITE_ENABLED="true")
    excluded = rows[99]
    scope = Snapshot.objects.filter(crawl=crawl).exclude(pk=excluded.pk).order_by()
    config = get_config(overrides={"SEARCH_BACKEND_ENGINE": "sqlite"})
    search = SnapshotSearch(scope, "planetary OR title:research", config=config, streaming=True)
    hits = list(search.stream())
    expected = {row.pk for row in rows if row.title == "research" and row.pk != excluded.pk} | {indexed.pk}
    assert set(hits) == expected and len(hits) == len(expected)
    assert not search.usage["bytes"]


@pytest.mark.django_db(transaction=True)
def test_index_only_sonic_hit_and_unknown_negative(crawl, tmp_path):
    import shlex
    import time

    from abx_plugins.plugins.search_backend_sonic.daemon import get_sonic_supervisord_worker, is_port_listening
    from archivebox.tests.conftest import get_free_port

    port = get_free_port()
    settings = {
        "SEARCH_BACKEND_ENGINE": "sonic",
        "SEARCH_BACKEND_SONIC_ENABLED": "true",
        "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
        "SEARCH_BACKEND_SONIC_PORT": str(port),
        "SEARCH_BACKEND_SONIC_PASSWORD": "search-test",
    }
    worker = get_sonic_supervisord_worker({"DATA_DIR": str(tmp_path), **settings})
    assert worker is not None
    with (tmp_path / "sonic-test.log").open("w") as log:
        daemon = subprocess.Popen(shlex.split(worker["command"]), cwd=worker["directory"], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while not is_port_listening("127.0.0.1", port):
                assert daemon.poll() is None, (tmp_path / "sonic-test.log").read_text()
                assert time.monotonic() < deadline, "Sonic did not reach its test socket"
                time.sleep(0.05)

            hit = Snapshot.objects.create(crawl=crawl, url="https://papers.example/indexed")
            missing = Snapshot.objects.create(crawl=crawl, url="https://papers.example/missing")
            output(hit, "article/content.txt", "interstellar magnetosphere")
            run_hook(hit, "search_backend_sonic", "--snapshot-id", str(hit.pk), **settings)
            # Only Sonic can find this word once the extraction is unavailable.
            (hit.output_dir / "article/content.txt").rename(tmp_path / "indexed-source.txt")
            config = get_config(overrides=settings)
            scope = Snapshot.objects.filter(pk__in=[hit.pk, missing.pk])
            assert list(SnapshotSearch(scope, "domain:papers.example interstellar", config=config).stream()) == [hit.pk]
            negative = SnapshotSearch(scope, "domain:papers.example ~interstellar", config=config)
            assert list(negative.stream()) == []
            assert negative.partial

            # A slow disk branch is never required to publish a Boolean result
            # already established by an index or metadata, even when it comes first.
            output(missing, "dom/large.txt", "unrelated " * 550_000 + "diskneedle")
            for expression in (
                "deep:diskneedle OR interstellar",
                "(deep:diskneedle AND title:missing) OR interstellar",
                "(absentlexeme OR interstellar) AND domain:papers.example",
                "interstellar AND magnetosphere",
                "magnetosphere AND (interstellar OR deep:diskneedle)",
                "interstellar AND ~title:missing",
            ):
                plan = SnapshotSearch(scope.order_by(), expression, config=config, streaming=True)
                stream = plan.stream()
                try:
                    assert next(stream) == hit.pk
                    assert plan.usage["bytes"] == 0
                finally:
                    stream.close()
            assert not list(SnapshotSearch(scope.exclude(pk=hit.pk), "magnetosphere AND interstellar", config=config).stream())
            # Neither source alone proves an AND, and a hit outside the
            # active scope never authorizes reading its directory.
            output(hit, "dom/content.txt", "diskneedle")
            plan = SnapshotSearch(scope.order_by(), "interstellar AND deep:diskneedle", config=config, streaming=True)
            stream = plan.stream()
            try:
                assert next(stream) == hit.pk
                assert plan.usage["bytes"] > 0
            finally:
                stream.close()

            from concurrent.futures import ThreadPoolExecutor
            from itertools import islice
            import signal
            import threading
            from django.db import connections

            # Stop the real index process mid-test. A slow index must not
            # prevent an independent SQL proof from filling the viewport.
            fast = Snapshot.objects.bulk_create(
                [
                    Snapshot(crawl=crawl, url=f"https://fast.example/{i}", title="screenful", timestamp=str(1800000000 + i))
                    for i in range(70)
                ],
            )
            expected = {row.pk for row in fast}
            for expression in (
                "domain:fast.example OR interstellar",
                "interstellar OR title:screenful",
                "domain:fast.example AND (screenful OR interstellar)",
                "(domain:fast.example AND ~title:missing) OR (interstellar AND deep:tail)",
            ):
                cancelled = threading.Event()

                def screen():
                    try:
                        plan = SnapshotSearch(
                            Snapshot.objects.filter(crawl=crawl).order_by(),
                            expression,
                            config=config,
                            streaming=True,
                            stop_event=cancelled,
                        )
                        stream = plan.stream()
                        try:
                            rows = list(islice(stream, 51))
                            assert plan.usage["bytes"] == 0
                            return rows
                        finally:
                            cancelled.set()
                            stream.close()
                    finally:
                        connections.close_all()

                daemon.send_signal(signal.SIGSTOP)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(screen)
                    try:
                        rows = result.result(timeout=3)
                        assert len(set(rows)) == 51 and set(rows) <= expected
                    finally:
                        cancelled.set()
                        daemon.send_signal(signal.SIGCONT)

        finally:
            daemon.terminate()
            daemon.wait(timeout=10)


def test_connected_search_reaches_late_snapshots_and_file_tails(crawl):
    config = get_config(overrides={"SEARCH_BACKEND_ENGINE": "ripgrep"})
    snapshots = []
    for i in range(16):
        snap = Snapshot.objects.create(id=UUID(int=i + 1), crawl=crawl, url=f"https://scan.example/{i}")
        output(snap, "dom/output.html", "available")
        snapshots.append(snap)
    # Cross both the 12-snapshot preview and the 512 KiB read boundary.
    # Place part of a UTF-8 literal on either side of the chunk boundary.
    (snapshots[-1].output_dir / "dom/output.html").write_bytes(b"x" * (512 * 1024 - 1) + "éclipse".encode())
    scope = Snapshot.objects.filter(pk__in=[s.pk for s in snapshots]).order_by("pk")
    search = SnapshotSearch(scope, 'deep:"éclipse"', config=config, streaming=True)
    assert list(search.stream()) == [snapshots[-1].pk]
    assert not search.partial


def test_connected_reverse_links_visit_late_sources_and_manifest_tail(crawl):
    sources = [Snapshot.objects.create(id=UUID(int=i + 1), crawl=crawl, url=f"https://sources.example/{i}") for i in range(15)]
    target = Snapshot.objects.create(crawl=crawl, url="https://late.example/end")
    entry = json.dumps({"url": target.url}) + "\n"
    output(sources[-1], "parse_html_urls/urls.jsonl", (json.dumps({"url": "https://early.example"}) + "\n") * 18000 + entry)
    scope = Snapshot.objects.filter(crawl=crawl)
    assert list(SnapshotSearch(scope, "linkedfrom:sources.example", streaming=True).stream()) == [target.pk]
    assert list(SnapshotSearch(scope, "linksto:late.example", streaming=True).stream()) == [sources[-1].pk]
