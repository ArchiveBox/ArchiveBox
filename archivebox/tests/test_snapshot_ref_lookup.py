import pytest
import uuid
from datetime import timedelta
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.views import _find_snapshot_by_ref
from archivebox.core.models import Snapshot
from archivebox.core.routes_util import get_web_host


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


@pytest.mark.django_db
def test_snapshot_prefix_lookup_preserves_unlisted_access_rules(snapshot, client):
    snapshot.config = {**(snapshot.config or {}), "PERMISSIONS": "unlisted"}
    snapshot.save(update_fields=["config"])
    prefix = snapshot.id.hex[:19]
    found = _find_snapshot_by_ref(prefix)
    assert found.id == snapshot.id
    assert found.matched_by_prefix is True

    # Guessable prefixes must not disclose the full ID, even in an auth redirect.
    path = "/" + snapshot.url_path.rsplit("/", 1)[0]
    response = client.get(f"{path}/{prefix}/", HTTP_HOST=get_web_host())
    assert response.status_code == 404
    assert "Location" not in response
    disclosed = response.content.decode() + str(dict(response.headers))
    assert str(snapshot.id) not in disclosed
    assert snapshot.id.hex not in disclosed

    # The complete unlisted reference continues to resolve without a login.
    response = client.get(f"{path}/{snapshot.id.hex}/", HTTP_HOST=get_web_host())
    assert response.status_code == 200
    assert snapshot.url.encode() in response.content
    response = client.get(f"{path}/{snapshot.id.hex[-12:]}/", HTTP_HOST=get_web_host())
    assert response.status_code == 302
    assert snapshot.id.hex in response["Location"]
    response = client.get(response["Location"], HTTP_HOST=get_web_host())
    assert response.status_code == 200
    assert snapshot.url.encode() in response.content


@pytest.mark.django_db
def test_unknown_short_numeric_snapshot_reference_returns_404(client):
    response = client.get("/web/20261013/example.com/1512629671342460931/", HTTP_HOST=get_web_host())
    assert response.status_code == 404
    assert b"1512629671342460931" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", ["anonymous", "member", "staff"])
@pytest.mark.parametrize("permissions", ["public", "unlisted", "private"])
@pytest.mark.parametrize("numeric", [False, True])
def test_legacy_archive_incomplete_ids_use_discovery_permissions(client, crawl, django_user_model, viewer, permissions, numeric):
    snapshot = Snapshot.objects.create(
        id=uuid.UUID("12345678912371238123456789123456" if numeric else "12345678abcd7abc8abcabcdef012345"),
        url="https://legacy-hidden.example/secret",
        title="Legacy hidden capture",
        crawl=crawl,
        config={"PERMISSIONS": permissions},
    )
    if viewer != "anonymous":
        user = django_user_model.objects.create_user(username="legacy-viewer", password="testpassword", is_staff=viewer == "staff")
        assert client.login(username=user.username, password="testpassword")

    references = [snapshot.id.hex[:8], snapshot.id.hex[:12], snapshot.id.hex[:19], snapshot.id.hex[-8:], snapshot.id.hex[-12:]]
    references += [str(snapshot.id)[:18].upper()]
    canonical_prefix = "/" + snapshot.url_path.rsplit("/", 1)[0]
    paths = [f"/archive/{reference}" for reference in references]
    paths += [
        canonical_prefix,
        f"{canonical_prefix}/{snapshot.id.hex[:19]}/",
        f"/snapshot/{snapshot.id.hex[:19]}/",
        f"/{crawl.created_by.username}/{snapshot.bookmarked_at:%Y%m%d}/{snapshot.url}",
    ]
    for path in paths:
        for method in (client.get, client.head):
            response = method(path, HTTP_HOST="admin.archivebox.localhost:5797")
            if permissions == "public" or viewer == "staff":
                if path.startswith("/snapshot/") and permissions == "private":
                    assert response.status_code == 200
                    if method == client.get:
                        assert snapshot.title.encode() in response.content
                else:
                    assert response.status_code == 302, (path, response.content)
                    assert snapshot.id.hex in response["Location"].replace("-", "")
            else:
                assert response.status_code == 404, (path, response.headers)
                assert "Location" not in response
                disclosed = response.content.decode() + str(dict(response.headers))
                for value in (str(snapshot.id), snapshot.id.hex, snapshot.timestamp, snapshot.title):
                    assert value not in disclosed
                if snapshot.url not in path:
                    assert snapshot.url not in disclosed

    # Knowing the entire UUID remains direct access, not discovery.
    for reference in (str(snapshot.id), snapshot.id.hex.upper()):
        response = client.get(f"/archive/{reference}", HTTP_HOST="admin.archivebox.localhost:5797")
        assert response.status_code == (404 if permissions == "private" and viewer != "staff" else 302)
        if response.status_code == 302:
            assert snapshot.id.hex in response["Location"].replace("-", "")

    # Exact legacy timestamps also retain their existing direct-access behavior.
    response = client.get(f"/archive/{snapshot.timestamp}", HTTP_HOST="admin.archivebox.localhost:5797")
    assert response.status_code == 302
    if permissions == "private" and viewer != "staff":
        assert "/admin/core/snapshot/replay-auth/" in response["Location"]
    else:
        assert snapshot.id.hex in response["Location"].replace("-", "")


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", ["anonymous", "member", "staff"])
@pytest.mark.parametrize("public_count", [0, 1, 2])
def test_legacy_archive_ambiguous_ids_only_list_discoverable_snapshots(client, crawl, django_user_model, viewer, public_count):
    snapshots = [
        Snapshot.objects.create(
            id=uuid.UUID(f"12345678abcd7abc8abc{index:012x}"),
            timestamp=f"1792583912.{index:06d}",
            url=f"https://legacy-{index}.example/secret",
            title=f"Legacy capture {index}",
            crawl=crawl,
            config={"PERMISSIONS": permissions},
        )
        for index, permissions in enumerate(["public"] * public_count + ["unlisted", "private"], start=1)
    ]
    if viewer != "anonymous":
        user = django_user_model.objects.create_user(username="legacy-viewer", password="testpassword", is_staff=viewer == "staff")
        assert client.login(username=user.username, password="testpassword")

    for reference in ("12345678", "12345678abcd", "1792583912", "legacy-"):
        response = client.get(f"/archive/{reference}", HTTP_HOST="admin.archivebox.localhost:5797")
        if public_count == 1 and viewer != "staff" and reference != "1792583912":
            assert response.status_code == 302
            assert snapshots[0].id.hex in response["Location"].replace("-", "")
            continue
        assert response.status_code == 404
        assert "Location" not in response
        disclosed = response.content.decode() + str(dict(response.headers))
        for snapshot in snapshots:
            visible = snapshot.permissions == "public" or viewer == "staff"
            assert (snapshot.url in disclosed) == visible
            assert (snapshot.id.hex in disclosed.replace("-", "")) == visible
            assert (snapshot.timestamp in disclosed) == visible
            assert (snapshot.title in disclosed) == visible
