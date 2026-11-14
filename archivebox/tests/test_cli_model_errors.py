"""Folder/importer CLI failures must leave records unchanged and avoid tracebacks."""

import json
from uuid import uuid4

import pytest

from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    "args",
    [
        ["folder", "get"],
        ["folder", "update", "--data", '{"name":"changed"}'],
        ["folder", "delete", "--yes"],
        ["importer", "get"],
        ["importer", "update", "--data", '{"name":"changed"}'],
        ["importer", "delete", "--yes"],
        ["importer", "action", "preview"],
        ["importer", "run"],
        ["importer", "runs", "--source-id"],
    ],
)
def test_missing_model_ids_are_cli_errors(initialized_archive, args):
    missing = str(uuid4())
    # Positional IDs precede the action name; the run-list filter takes an option.
    command = [*args[:2], missing, *args[2:]] if args[1] != "runs" else [*args, missing]
    result = run_archivebox_cmd(command, cwd=initialized_archive, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "not found" in result.stderr.lower(), result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout.strip()


@pytest.mark.parametrize("bad_target", ["folder", "snapshot"])
def test_move_missing_references_does_not_move_any_snapshot(initialized_archive, bad_target):
    with use_archivebox_db(initialized_archive):
        folder = Folder.objects.create(name="Move destination")
        crawl = Crawl.objects.create(urls="https://example.com/")
        snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/")
        folder_ids = set(Folder.objects.values_list("pk", flat=True))
    missing = str(uuid4())
    command = ["folder", "move-snapshots", str(snapshot.pk)]
    if bad_target == "snapshot":
        command.append(missing)
    command.extend(["--destination-id", missing if bad_target == "folder" else str(folder.pk)])
    result = run_archivebox_cmd(command, cwd=initialized_archive, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "not found" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    with use_archivebox_db(initialized_archive):
        snapshot.refresh_from_db()
        assert snapshot.folder_id is None
        assert set(Folder.objects.values_list("pk", flat=True)) == folder_ids


@pytest.mark.parametrize(
    "payload",
    [
        '{"name":',
        "[]",
        '{"parent_id":"not-a-uuid"}',
        '{"position":null}',
        '{"name":null}',
        '{"parent_id":{}}',
        '{"parent_id":{"id":"bad"}}',
        '{"rules":[]}',
    ],
)
def test_invalid_folder_updates_preserve_record(initialized_archive, payload):
    with use_archivebox_db(initialized_archive):
        folder = Folder.objects.create(name="Unchanged")
    result = run_archivebox_cmd(["folder", "update", str(folder.pk), "--data", payload], cwd=initialized_archive, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Error:" in result.stderr and "Traceback" not in result.stderr
    with use_archivebox_db(initialized_archive):
        folder.refresh_from_db()
        assert folder.name == "Unchanged" and folder.parent_id is None and folder.position == 0


@pytest.mark.parametrize("rules", ['{"field":', "[]", "false", '{"field":"bogus","lookup":"exact","value":"x"}'])
def test_invalid_smart_folder_rules_do_not_create_record(initialized_archive, rules):
    result = run_archivebox_cmd(["folder", "create", "Invalid", "--rules", rules], cwd=initialized_archive, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Error:" in result.stderr and "Traceback" not in result.stderr
    with use_archivebox_db(initialized_archive):
        assert not Folder.objects.filter(name="Invalid").exists()


def test_importer_reference_and_json_errors_preserve_source(initialized_archive):
    from archivebox.importers.models import ImporterSource

    result = run_archivebox_cmd(
        [
            "importer",
            "create",
            "--plugin",
            "importer_rss",
            "--feed",
            "feed",
            "--name",
            "Unchanged",
            "--settings",
            '{"IMPORTER_RSS_URL":"https://example.com/feed.xml"}',
        ],
        cwd=initialized_archive,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    source = json.loads(result.stdout)
    for payload in (
        '{"name":',
        '{"settings":[]}',
        json.dumps({"name": "Changed", "folder_id": str(uuid4())}),
        json.dumps({"persona_id": str(uuid4())}),
    ):
        result = run_archivebox_cmd(["importer", "update", source["id"], "--data", payload], cwd=initialized_archive, timeout=30)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Error:" in result.stderr and "Traceback" not in result.stderr
        with use_archivebox_db(initialized_archive):
            saved = ImporterSource.objects.get(pk=source["id"])
            assert saved.name == "Unchanged" and saved.folder_id is None and saved.persona_id is None


def test_move_accepts_duplicate_uuid_spellings_and_native_destinations(initialized_archive):
    from uuid import UUID

    with use_archivebox_db(initialized_archive):
        parent = Folder.objects.create(name="Parent destination")
        Folder.objects.create(name="Existing child", parent=parent)
        smart = Folder.objects.create(name="Smart destination", rules={"field": "title", "lookup": "icontains", "value": "news"})
        crawl = Crawl.objects.create(urls="https://example.com/")
        snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/")
    result = run_archivebox_cmd(
        ["folder", "move-snapshots", snapshot.pk.hex, str(UUID(snapshot.pk.hex)), "--destination-id", str(parent.pk)],
        cwd=initialized_archive,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"moved": 1}
    with use_archivebox_db(initialized_archive):
        snapshot.refresh_from_db()
        destination_id = snapshot.folder_id
        assert snapshot.folder.name == "Items" and snapshot.folder.parent_id == parent.pk
    result = run_archivebox_cmd(
        ["folder", "move-snapshots", str(snapshot.pk), "--destination-id", str(smart.pk)],
        cwd=initialized_archive,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Choose a regular folder" in result.stderr and "Traceback" not in result.stderr
    with use_archivebox_db(initialized_archive):
        snapshot.refresh_from_db()
        assert snapshot.folder_id == destination_id
