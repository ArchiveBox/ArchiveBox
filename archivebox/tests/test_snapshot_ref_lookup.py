import pytest
import uuid
from datetime import timedelta
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.views import _find_snapshot_by_ref
from archivebox.core.models import Snapshot


@pytest.mark.django_db
def test_snapshot_suffix_lookup_scans_covering_id_index(snapshot):
    suffix = str(snapshot.id).replace("-", "")[-12:]
    with CaptureQueriesContext(connection) as queries:
        found = _find_snapshot_by_ref(suffix)
    assert found.id == snapshot.id
    assert found.crawl.created_by_id == snapshot.crawl.created_by_id
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN QUERY PLAN " + queries[0]["sql"])
        plan = " ".join(str(row[-1]) for row in cursor.fetchall())
    assert "COVERING INDEX" in plan, plan
    assert _find_snapshot_by_ref("000000000000") is None


@pytest.mark.django_db
def test_snapshot_suffix_collision_keeps_newest_match(snapshot):
    suffix = str(snapshot.id).replace("-", "")[-12:]
    other = Snapshot.objects.create(
        id=uuid.UUID("ffffffffffffffffffff" + suffix),
        url="https://example.org/other",
        crawl=snapshot.crawl,
    )
    Snapshot.objects.filter(pk=other.pk).update(created_at=snapshot.created_at + timedelta(seconds=1))
    assert _find_snapshot_by_ref(suffix).id == other.id
    assert _find_snapshot_by_ref(str(snapshot.id)).id == snapshot.id


@pytest.mark.django_db(transaction=True)
def test_snapshot_suffix_lookup_reuses_resolved_pk_but_rereads_row(snapshot):
    suffix = str(snapshot.id).replace("-", "")[-12:]
    assert _find_snapshot_by_ref(suffix).id == snapshot.id

    # Permission edits must apply on the very next snap-* request.
    snapshot.config = {**(snapshot.config or {}), "PERMISSIONS": "private"}
    snapshot.save(update_fields=["config"])
    with CaptureQueriesContext(connection) as queries:
        found = _find_snapshot_by_ref(suffix)
    assert found.id == snapshot.id
    assert found.permissions == "private"
    assert len(queries) == 1
    assert "LIKE" not in queries[0]["sql"].upper()

    Snapshot.objects.filter(pk=snapshot.pk).delete()
    assert _find_snapshot_by_ref(suffix) is None


@pytest.mark.django_db(transaction=True)
def test_snapshot_suffix_lookup_does_not_cache_ambiguous_or_prefix_matches(snapshot):
    suffix = str(snapshot.id).replace("-", "")[-12:]
    other = Snapshot.objects.create(
        id=uuid.UUID("eeeeeeeeeeeeeeeeeeee" + suffix),
        url="https://example.org/ambiguous",
        crawl=snapshot.crawl,
    )
    Snapshot.objects.filter(pk=other.pk).update(created_at=snapshot.created_at + timedelta(seconds=1))
    assert _find_snapshot_by_ref(suffix).id == other.id
    Snapshot.objects.filter(pk=other.pk).delete()
    assert _find_snapshot_by_ref(suffix).id == snapshot.id

    # A 12-hex *prefix* is not a suffix: it must never resolve as an unlisted link.
    prefix = str(snapshot.id).replace("-", "")[:12]
    assert _find_snapshot_by_ref(prefix) is None
