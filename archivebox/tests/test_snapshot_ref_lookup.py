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
