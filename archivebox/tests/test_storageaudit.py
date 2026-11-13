"""Audit real files, manifests, and native capture records without substitute storage."""

from pathlib import Path

import pytest
from archivebox.tests.conftest import ADMIN_TEST_HOST, run_test_hook

pytestmark = pytest.mark.django_db(transaction=True)


def hashed_snapshot(user, tmp_path, name):
    from importlib.resources import files
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=user, config={"PLUGINS": "hashes"})
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed")
    root = snapshot.output_dir
    (root / "original").mkdir(parents=True)
    source = Path(__file__).parent / "fixtures" / "legacy_proofs" / "opentimestamps" / "stamp-tc1mgx85" / "hashes.json"
    (root / "original" / name).write_bytes(source.read_bytes())
    hook = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
    process = run_test_hook(
        hook,
        root / "hashes",
        config={"SNAP_DIR": str(root), "ABXPKG_LIB_DIR": str(tmp_path / "lib")},
        url=snapshot.url,
        timeout=30,
    )
    assert process.exit_code == 0, process.stderr
    assert (root / "hashes" / "hashes.sha256").is_file()
    return snapshot


def test_audit_finds_cross_snapshot_files_and_preserves_versions(admin_user, tmp_path):
    from archivebox.storageaudit.service import audit_files
    from archivebox.core.models import Snapshot

    first = hashed_snapshot(admin_user, tmp_path, "page.json")
    second = hashed_snapshot(admin_user, tmp_path, "another.json")
    report = audit_files(Snapshot.objects.filter(pk__in=[first.pk, second.pk]))
    assert report["complete"]
    group = next(group for group in report["groups"] if any(file["path"].endswith("page.json") for file in group["files"]))
    assert {file["snapshot_id"] for file in group["files"]} == {str(first.pk), str(second.pk)}
    assert group["potential_bytes"] == group["size"] > 0
    assert Snapshot.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert all(Path(file["absolute_path"]).is_file() for file in group["files"])


def test_audit_rejects_changed_files_and_unpublished_manifests(admin_user, tmp_path):
    from archivebox.storageaudit.service import audit_files
    from archivebox.core.models import Snapshot

    item = hashed_snapshot(admin_user, tmp_path, "page.json")
    (item.output_dir / "original" / "page.json").write_text("changed after hashing")
    report = audit_files(Snapshot.objects.filter(pk=item.pk))
    assert report["stale_files"] >= 1
    assert report["groups"] == []
    (item.output_dir / "hashes" / "hashes.sha256").unlink()
    report = audit_files(Snapshot.objects.filter(pk=item.pk))
    assert report["missing_manifests"] == 1


def test_storage_audit_permissions_and_native_version_counts(admin_client, admin_user):
    from django.test import Client
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    for _ in range(2):
        crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
        Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed")
    response = admin_client.get("/admin/storage-audit/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["versions"][0]["captures"] == 2
    assert Client().get("/admin/storage-audit/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302


def test_storage_audit_command_reads_real_outputs_and_guards_selection(admin_client, admin_user, tmp_path):
    from io import StringIO
    import json
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.test import Client

    hashed_snapshot(admin_user, tmp_path, "first.json")
    hashed_snapshot(admin_user, tmp_path, "second.json")
    output = StringIO()
    call_command("storageaudit", user=admin_user.pk, stdout=output)
    report = json.loads(output.getvalue().splitlines()[-1])
    assert report["complete"] and report["groups"]
    assert report["potential_bytes"] > 0
    assert admin_client.post("/admin/storage-audit/preview/", {"run": "invalid"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    assert admin_client.post("/admin/storage-audit/apply/", {"preview": "tampered"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    staff = get_user_model().objects.create_user(username="audit-viewer", password="test-password", is_staff=True)
    client = Client()
    client.force_login(staff)
    for path in ("scan/", "preview/", "apply/"):
        assert client.post("/admin/storage-audit/" + path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_output_manifest_fallback_and_path_boundaries(admin_user, tmp_path):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.storageaudit.service import audit_files, output_file

    snapshot = hashed_snapshot(admin_user, tmp_path, "page.json")
    (snapshot.output_dir / "hashes" / "hashes.json").unlink()
    path = snapshot.output_dir / "original" / "page.json"
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="original",
        hook_name="on_Snapshot__01_original.py",
        status="succeeded",
        output_files={"page.json": {"size": path.stat().st_size}},
    )
    report = audit_files(Snapshot.objects.filter(pk=snapshot.pk))
    assert report["output_manifests"] == 1 and report["files"] == 1
    with pytest.raises(ValueError):
        output_file(snapshot, "../index.sqlite3")
    with pytest.raises(ValueError):
        output_file(snapshot, "chrome/chrome_profile/Default/Preferences")
    with pytest.raises(ValueError):
        output_file(snapshot, "chrome/browser.json")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (snapshot.output_dir / "original" / "linked.txt").symlink_to(outside)
    with pytest.raises(ValueError):
        output_file(snapshot, "original/linked.txt")


def test_storage_rankings_use_recorded_sizes_and_completed_hook_runtimes(admin_client, admin_user):
    from datetime import timedelta
    from django.utils import timezone
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine, Process
    from archivebox.tests.test_snapshot_output_stacks import save_output

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    start = timezone.now()
    plugins = [
        "wget",
        "singlefile",
        "screenshot",
        "pdf",
        "readability",
        "defuddle",
        "htmltotext",
        "title",
        "favicon",
        "headers",
        "dns",
        "responses",
    ]
    snapshots = []
    expected_sizes = {}
    for index, plugin in enumerate(plugins):
        snapshot = Snapshot.objects.create(url=f"https://news.ycombinator.com/item?id={index}", crawl=crawl, title=plugin, status="sealed")
        snapshots.append(snapshot)
        result = save_output(snapshot, plugin, extra_files=tuple(f"asset-{n}.html" for n in range(index)))
        expected_sizes[plugin] = result.output_size
        process = Process.objects.create(
            machine=Machine.current(),
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            started_at=start,
            ended_at=start + timedelta(seconds=index + 1),
            exit_code=0,
        )
        ArchiveResult.objects.filter(pk=result.pk).update(process=process, start_ts=start, end_ts=start + timedelta(seconds=500))
    second = save_output(snapshots[0], "wget", filename="second.html", hook="60")
    ArchiveResult.objects.filter(pk=second.pk).update(start_ts=start, end_ts=start + timedelta(seconds=30))
    expected_sizes["wget"] += second.output_size
    pending = save_output(snapshots[0], "git")
    ArchiveResult.objects.filter(pk=pending.pk).update(start_ts=start - timedelta(days=2), end_ts=None, status="started")
    invalid = save_output(snapshots[0], "mercury")
    ArchiveResult.objects.filter(pk=invalid.pk).update(start_ts=start, end_ts=start - timedelta(seconds=1))

    response = admin_client.get("/admin/storage-audit/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    slowest = response.context["slowest_plugins"]
    assert len(slowest) == 10 and slowest[0]["plugin"] == "wget"
    assert {key: slowest[0][key] for key in ("count", "total_seconds", "avg_seconds", "max_seconds")} == {
        "count": 2,
        "total_seconds": 31,
        "avg_seconds": 15.5,
        "max_seconds": 30,
    }
    assert slowest[1]["plugin"] == "responses" and slowest[1]["max_seconds"] == 12
    assert not {"git", "mercury"}.intersection(row["plugin"] for row in slowest)
    heaviest = response.context["heaviest_plugins"]
    assert len(heaviest) == 10 and heaviest[0]["plugin"] == "responses"
    assert all(row["bytes"] == expected_sizes[row["plugin"]] for row in heaviest)
    largest = response.context["largest_snapshots"]
    assert len(largest) == 10 and str(largest[0]["id"]) == str(snapshots[-1].pk)
    assert largest[0]["bytes"] == expected_sizes["responses"] and largest[0]["output_count"] == 1
    for row in [*slowest, *heaviest, *largest]:
        assert row["review_url"].startswith("/admin/core/")
    filtered = admin_client.get("/admin/storage-audit/", {"q": "item?id=0"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert len(filtered.context["largest_snapshots"]) == 1
    assert [row["plugin"] for row in filtered.context["slowest_plugins"]] == ["wget"]


def test_extension_totals_allocate_each_redundant_inode_once(admin_user, tmp_path):
    import os
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.storageaudit.service import audit_files, group_extensions

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed")
    directory = snapshot.output_dir / "original"
    directory.mkdir(parents=True)
    source = Path(__file__).parent / "fixtures" / "legacy_proofs" / "opentimestamps" / "stamp-tc1mgx85" / "hashes.json"
    content = source.read_bytes()
    for name in ("a.json", "b.JSON", "c.txt", "no-extension"):
        (directory / name).write_bytes(content)
    os.link(directory / "c.txt", directory / "d.txt")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="original",
        hook_name="on_Snapshot__01_original.py",
        status="succeeded",
        output_files={path.name: {"size": path.stat().st_size} for path in directory.iterdir()},
    )
    report = audit_files(Snapshot.objects.filter(pk=snapshot.pk))
    extensions = group_extensions(report["groups"])
    by_extension = {row["extension"]: row for row in extensions}
    assert set(by_extension) == {".json", ".txt", "(none)"}
    assert sum(row["potential_bytes"] for row in extensions) == report["potential_bytes"] == 3 * len(content)
    assert by_extension[".json"]["file_count"] == 2
    assert by_extension[".txt"]["file_count"] == 2
    assert all(row["group_count"] == 1 and row["potential_bytes"] == len(content) for row in extensions)
    assert all(row["groups"][0]["files"] == report["groups"][0]["files"] for row in extensions)


def test_extension_bulk_review_uses_native_scan_and_compact_signed_selection(admin_client, admin_user):
    import os
    import sys
    from io import StringIO
    from django.core import signing
    from django.core.management import CommandError, call_command
    from django.db import connection
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process
    from archivebox.storageaudit.service import file_digest, group_selection_hash, read_report

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed")
    directory = snapshot.output_dir / "original"
    directory.mkdir(parents=True)
    source = Path(__file__).parent / "fixtures" / "legacy_proofs" / "opentimestamps" / "stamp-tc1mgx85" / "hashes.json"
    content = source.read_bytes()
    for index in range(101):
        for copy in ("a", "b"):
            (directory / f"{index:03}-{copy}.json").write_bytes(content + b"\n" * index)
    paths = list(directory.iterdir())
    before = {path: file_digest(path) for path in paths}
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="original",
        hook_name="on_Snapshot__01_original.py",
        status="succeeded",
        output_files={path.name: {"size": path.stat().st_size} for path in paths},
    )
    other = Snapshot.objects.create(url="https://example.com/", crawl=crawl, status="sealed")
    other_directory = other.output_dir / "original"
    other_directory.mkdir(parents=True)
    for name in ("a.json", "b.json"):
        (other_directory / name).write_bytes(content + b"\n" * 102)
    ArchiveResult.objects.create(
        snapshot=other,
        plugin="original",
        hook_name="on_Snapshot__01_original.py",
        status="succeeded",
        output_files={path.name: {"size": path.stat().st_size} for path in other_directory.iterdir()},
    )
    # The real background management command must use this test's real database.
    previous = os.environ.get("DATABASE_NAME")
    os.environ["DATABASE_NAME"] = str(connection.settings_dict["NAME"])
    try:
        response = admin_client.post("/admin/storage-audit/scan/", HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 302
        process = Process.objects.get(pk=response["Location"].split("run=")[1])
        assert process.wait(timeout=30) == 0, process.stderr
        process.refresh_from_db()
        report = read_report(process)
        assert report["complete"] and len(report["groups"]) == 102
        response = admin_client.post(
            "/admin/storage-audit/preview/",
            {"run": str(process.pk), "extension": ".json", "q": "ycombinator"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 200
        groups = response.context["groups"]
        assert len(groups) == 101 and sum(len(group["files"]) for group in groups) == 202
        token = response.context["token"]
        payload = signing.loads(token, salt="storage-audit-cow")
        assert payload == {"run": str(process.pk), "extension": ".json", "q": "ycombinator", "selection_hash": group_selection_hash(groups)}
        assert len(token) < 400
        assert (
            admin_client.post(
                "/admin/storage-audit/preview/",
                {"run": str(process.pk), "extension": ".missing"},
                HTTP_HOST=ADMIN_TEST_HOST,
            ).status_code
            == 400
        )
        assert (
            admin_client.post(
                "/admin/storage-audit/preview/",
                {"run": str(process.pk), "extension": ".json", "groups": [groups[0]["id"]]},
                HTTP_HOST=ADMIN_TEST_HOST,
            ).status_code
            == 400
        )
        with pytest.raises(CommandError, match="selection changed"):
            call_command(
                "storageaudit", user=admin_user.pk, source=str(process.pk), extension=".json", selection_hash="0" * 64, stdout=StringIO()
            )
        applied = admin_client.post("/admin/storage-audit/apply/", {"preview": token}, HTTP_HOST=ADMIN_TEST_HOST)
        if sys.platform == "linux":
            assert applied.status_code == 302
            operation = Process.objects.get(pk=applied["Location"].split("run=")[1])
            assert "--extension" in operation.cmd and "--group" not in operation.cmd
            assert operation.cmd[-2:] == ["--query", "ycombinator"]
            assert operation.wait(timeout=30) == 0, operation.stderr
            result = read_report(operation)
            assert result["operation"] == "copy-on-write" and result["groups"] == 101
            assert result["result"]["attempted_files"] == 101
        else:
            assert applied.status_code == 400 and b"requires Linux" in applied.content
            with pytest.raises(CommandError, match="requires Linux"):
                call_command(
                    "storageaudit",
                    user=admin_user.pk,
                    source=str(process.pk),
                    extension=".json",
                    selection_hash=payload["selection_hash"],
                    query="ycombinator",
                    stdout=StringIO(),
                )
        assert {path: file_digest(path) for path in paths} == before
    finally:
        if previous is None:
            os.environ.pop("DATABASE_NAME", None)
        else:
            os.environ["DATABASE_NAME"] = previous
