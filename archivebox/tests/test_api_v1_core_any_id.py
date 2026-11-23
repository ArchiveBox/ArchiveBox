import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/any", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/any", crawl=crawl)

    response = client.get(f"/api/v1/core/any/{snapshot.id}", follow=True, **api_headers)

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("model_name", ["snapshot", "archiveresult", "tag", "crawl"])
def test_lookup_database_failure_is_logged_and_not_reported_as_missing(client, api_admin_user, api_headers, caplog, model_name):
    import logging

    from django.db import connection, OperationalError, ProgrammingError
    from archivebox.core.models import ArchiveResult, Tag

    crawl = Crawl.objects.create(urls="https://example.com/lookup-failure", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="dom", hook_name="on_Snapshot__dom")
    tag = Tag.objects.create(name="lookup-database-failure", created_by=api_admin_user)
    obj = {"snapshot": snapshot, "archiveresult": result, "tag": tag, "crawl": crawl}[model_name]
    ref = tag.name if obj is tag else str(obj.pk)
    table = connection.ops.quote_name(obj._meta.db_table)
    unavailable = connection.ops.quote_name(f"{obj._meta.db_table}_unavailable")
    # Remove the real lookup table only inside this disposable test database.
    # Authentication still succeeds; the selected getter must hit the actual DB.
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} RENAME TO {unavailable}")
    try:
        response = client.get(f"/api/v1/core/any/{ref}", **api_headers)
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {unavailable} RENAME TO {table}")

    assert response.status_code == 503, response.content
    records = [record for record in caplog.records if record.name == "archivebox.api.v1_api"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], (OperationalError, ProgrammingError))
    assert records[0].exc_info[2] is not None
    recovered = client.get(f"/api/v1/core/any/{ref}", **api_headers)
    assert recovered.status_code == 302, recovered.content
    assert recovered.url == f"/api/v1/{obj._meta.app_label}/{obj._meta.model_name}/{obj.pk}?"


@pytest.mark.parametrize(
    "model_name,reference",
    [
        ("snapshot", "uuid"),
        ("snapshot", "hex"),
        ("snapshot", "prefix"),
        ("snapshot", "timestamp"),
        ("archiveresult", "uuid"),
        ("archiveresult", "hex"),
        ("archiveresult", "prefix"),
        ("crawl", "uuid"),
        ("crawl", "hex"),
        ("crawl", "prefix"),
        ("crawl", "suffix"),
        ("tag", "id"),
        ("tag", "name"),
        ("tag", "uppercase"),
    ],
)
def test_any_reference_formats_preserve_target_and_query(client, api_admin_user, api_headers, model_name, reference):
    from archivebox.core.models import ArchiveResult, Tag

    crawl = Crawl.objects.create(urls="https://example.com/reference", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="dom", hook_name="on_Snapshot__dom")
    tag = Tag.objects.create(id=987654321, name="any-reference", created_by=api_admin_user)
    obj = {"snapshot": snapshot, "archiveresult": result, "tag": tag, "crawl": crawl}[model_name]
    ref = str(obj.pk)
    if reference == "hex":
        ref = ref.replace("-", "")
    elif reference == "prefix":
        ref = ref.replace("-", "")[:16]
    elif reference == "suffix":
        ref = ref.replace("-", "")[-12:]
    elif reference == "timestamp":
        ref = snapshot.timestamp
    elif reference in ("name", "uppercase"):
        ref = tag.name.upper() if reference == "uppercase" else tag.name
    response = client.get(f"/api/v1/core/any/{ref}?with_snapshots=false", **api_headers)
    assert response.status_code == 302, response.content
    assert response.url == f"/api/v1/{obj._meta.app_label}/{obj._meta.model_name}/{obj.pk}?with_snapshots=false"


def test_ambiguous_reference_can_resolve_another_type(client, api_admin_user, api_headers):
    from uuid import UUID
    from archivebox.core.models import Tag

    crawl = Crawl.objects.create(urls="https://example.com/ambiguous", created_by=api_admin_user)
    for suffix in (1, 2):
        Snapshot.objects.create(id=UUID(f"aaaaaaaa-0000-0000-0000-{suffix:012d}"), url=f"{crawl.urls}/{suffix}", crawl=crawl)
    tag = Tag.objects.create(name="aaaaaaaa", created_by=api_admin_user)
    response = client.get("/api/v1/core/any/aaaaaaaa", **api_headers)
    assert response.status_code == 302, response.content
    assert response.url == f"/api/v1/core/tag/{tag.pk}?"
    tag.delete()
    assert client.get("/api/v1/core/any/aaaaaaaa", **api_headers).status_code == 404


@pytest.mark.parametrize("reference", ["missing-record", "not-a-valid-uuid", "00000000-0000-0000-0000-000000000000"])
def test_missing_reference_still_returns_not_found(client, api_headers, reference):
    response = client.get(f"/api/v1/core/any/{reference}", **api_headers)
    assert response.status_code == 404


def test_any_lookup_still_requires_authentication(client, api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/private", created_by=api_admin_user)
    response = client.get(f"/api/v1/core/any/{crawl.pk}", HTTP_HOST="api.archivebox.localhost")
    assert response.status_code == 401
