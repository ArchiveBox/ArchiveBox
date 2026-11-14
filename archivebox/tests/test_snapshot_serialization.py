"""The snapshot export adapters preserve their schemas around shared metadata."""

import csv
import io
import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.cli.archivebox_snapshot import iter_snapshot_json
from archivebox.core.exports import EXPORT_FIELDS, write_snapshot_metadata
from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def serialized_snapshot(api_admin_user):
    folder = Folder.objects.create(name='Research, "quoted"', created_by=api_admin_user)
    persona = Persona.objects.create(name="Export persona", created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user, persona=persona)
    snapshot = Snapshot.objects.create(
        crawl=crawl,
        folder=folder,
        url="https://example.com/",
        title='Title, "quoted"\nsecond line',
        output_size=123,
        status="sealed",
        downloaded_at=timezone.now(),
        config={"API_KEY": "private-secret", "PERMISSIONS": "public"},
        notes="Private notes",
    )
    snapshot.save_tags(["Zulu", "Comma, tag", "éclair"])
    return snapshot


def test_snapshot_serializers_preserve_metadata_and_boundary_shapes(serialized_snapshot):
    snapshot = serialized_snapshot
    record = snapshot.to_json()
    batch = list(iter_snapshot_json(Snapshot.objects.filter(pk=snapshot.pk)))
    assert batch == [record]
    assert set(record) == set(EXPORT_FIELDS) | {"config", "notes"}
    assert record["folder_id"] == str(snapshot.folder_id)
    assert record["folder_name"] == snapshot.folder.name
    assert record["persona_id"] == str(snapshot.crawl.persona_id)
    assert record["created_by_id"] == snapshot.crawl.created_by_id
    assert record["created_by_username"] == snapshot.crawl.created_by.username
    assert record["downloaded_at"] == snapshot.downloaded_at.isoformat()
    assert record["archive_size"] == record["output_size"] == 123
    assert record["config"] == {"API_KEY": "********", "PERMISSIONS": "public"}
    assert snapshot.config["API_KEY"] == "private-secret"
    assert record["tags"] == "Comma, tag,Zulu,éclair"

    legacy = snapshot.to_dict()
    assert legacy["TYPE"] == "core.models.Snapshot"
    assert legacy["tags"] == ["Comma, tag", "Zulu", "éclair"]
    assert not {"config", "notes", "type", "schema_version"}.intersection(legacy)
    for key in set(record).intersection(legacy) - {"tags"}:
        assert legacy[key] == record[key], key
    assert snapshot.to_dict(extended=True) == legacy
    static = snapshot.to_dict(static_export=True)
    assert static["archive_path"] == snapshot.static_archive_path
    assert static["archive_url"] == f"./{snapshot.static_archive_path}/index.html"


def test_legacy_snapshot_metadata_does_not_load_private_fields(serialized_snapshot):
    snapshot = (
        Snapshot.objects.select_related("folder", "crawl__created_by", "crawl__persona")
        .defer("config", "notes")
        .get(pk=serialized_snapshot.pk)
    )
    snapshot.to_dict()
    snapshot.to_csv(cols=["id", "title", "tags", "folder_name"])
    assert {"config", "notes"}.issubset(snapshot.get_deferred_fields())


def test_snapshot_csv_adapters_preserve_quotes_and_tag_shapes(serialized_snapshot):
    snapshot = serialized_snapshot
    legacy = list(csv.reader(io.StringIO(snapshot.to_csv(cols=["title", "folder_name", "tags"]))))
    assert legacy == [[snapshot.title, snapshot.folder.name, r'["Comma, tag", "Zulu", "\u00e9clair"]']]
    output = io.StringIO()
    write_snapshot_metadata(Snapshot.objects.filter(pk=snapshot.pk), "csv", output)
    row = next(csv.DictReader(io.StringIO(output.getvalue())))
    assert row["title"] == snapshot.title
    assert row["folder_name"] == snapshot.folder.name
    assert row["tags"] == "Comma, tag,Zulu,éclair"
    assert "private-secret" not in output.getvalue() and "Private notes" not in output.getvalue()


def test_snapshot_batch_serialization_uses_bounded_queries(api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshots = [Snapshot.objects.create(crawl=crawl, url=f"https://example.com/{index}") for index in range(5)]
    for snapshot in snapshots:
        snapshot.save_tags(["shared"])
    queryset = Snapshot.objects.filter(crawl=crawl).order_by("url")
    with CaptureQueriesContext(connection) as queries:
        records = list(iter_snapshot_json(queryset))
    assert len(queries) == 2, [query["sql"] for query in queries]
    assert len(records) == 5
    assert all(record["folder_id"] is None and record["persona_id"] is None and record["downloaded_at"] is None for record in records)
    assert all(record["tags"] == "shared" for record in records)


def test_snapshot_size_serialization_uses_current_saved_metadata(serialized_snapshot):
    snapshot = serialized_snapshot
    assert snapshot.archive_size == 123
    snapshot.output_size = 456
    snapshot.save(update_fields=["output_size"])
    expected = list(iter_snapshot_json(Snapshot.objects.filter(pk=snapshot.pk)))[0]
    assert snapshot.to_json() == expected
    assert snapshot.to_dict()["archive_size"] == snapshot.to_dict()["output_size"] == 456


@pytest.mark.parametrize("with_relations", [True, False])
def test_snapshot_rest_and_exports_share_relationship_metadata(serialized_snapshot, client, api_headers, with_relations):
    snapshot = serialized_snapshot
    if not with_relations:
        snapshot.folder = None
        snapshot.save(update_fields=["folder"])
        snapshot.crawl.persona = None
        snapshot.crawl.save(update_fields=["persona"])
    expected = snapshot.to_json()
    for url, query in (
        (f"/api/v1/core/snapshot/{snapshot.pk}", {}),
        ("/api/v1/core/snapshots", {"crawl_id": str(snapshot.crawl_id)}),
    ):
        response = client.get(url, query, **api_headers)
        assert response.status_code == 200, response.content
        body = response.json()
        record = body["items"][0] if "items" in body else body
        for field in (
            "id",
            "crawl_id",
            "folder_id",
            "folder_name",
            "persona_id",
            "persona_name",
            "created_by_username",
            "output_size",
            "archive_size",
        ):
            assert record[field] == expected[field], field
        assert record["persona"] == expected["persona_name"]
        assert record["created_by_id"] == str(expected["created_by_id"])
        assert record["tags"] == ["Comma, tag", "Zulu", "éclair"]
        assert "config" not in record and "notes" not in record
    for format in ("csv", "jsonl"):
        response = client.get(
            f"/api/v1/core/snapshots/export/{format}",
            {"crawl_id": str(snapshot.crawl_id)},
            **api_headers,
        )
        assert response.status_code == 200, response.content
        record = next(csv.DictReader(io.StringIO(response.content.decode()))) if format == "csv" else json.loads(response.content)
        for field in ("folder_id", "folder_name", "persona_id", "persona_name", "created_by_id", "created_by_username"):
            value = expected[field]
            if format == "csv":
                value = str(value) if value is not None else ""
            assert record[field] == value, field
