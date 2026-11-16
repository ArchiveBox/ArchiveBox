"""Bounded, immutable deletion confirmation using real admin POSTs and rows."""

import time
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from archivebox.core.models import Snapshot, ArchiveResult
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_large_delete_confirmation_is_bounded_and_immutable(admin_client, crawl):
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(crawl=crawl, url=f"https://delete-fixture.test/{i}", timestamp=str(1800000000 + i), status="sealed")
            for i in range(14273)
        ],
    )
    ArchiveResult.objects.bulk_create(
        [ArchiveResult(snapshot=s, plugin="dom", status="succeeded", output_str="dom/output.html") for s in rows[:3000]],
    )
    endpoint = "/admin/core/snapshot/?domain=delete-fixture.test"
    data = {"action": "delete_selected", "select_across": "1", "_selected_action": [str(rows[0].pk)]}
    started = time.monotonic()
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.post(endpoint, data, HTTP_HOST=ADMIN_TEST_HOST)
    elapsed = time.monotonic() - started
    captured_queries = list(queries)
    assert response.status_code == 200
    assert response.context["count"] == 14273
    assert len(response.context["preview"]) == 20
    assert len(response.content) < 800000
    child_queries = [q["sql"] for q in captured_queries if "core_archiveresult" in q["sql"]]
    # Native changelist prepares one bounded page before dispatching the action.
    assert len(child_queries) <= 1
    assert all(sql.count("', '") < 100 for sql in child_queries)
    assert not any("machine_process" in q["sql"] for q in captured_queries)
    assert Snapshot.objects.filter(status="deleting").count() == 0
    new = Snapshot.objects.create(crawl=crawl, url="https://delete-fixture.test/new", status="sealed")
    outside = Snapshot.objects.create(crawl=crawl, url="https://outside-fixture.test/keep", status="sealed")
    assert admin_client.post(endpoint, {**data, "post": "yes"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    # A formerly selected row that no longer matches the authorized filter
    # is excluded on confirmation, just as a newly matching row is not added.
    Snapshot.objects.filter(pk=rows[-1].pk).update(url="https://outside-fixture.test/moved")
    token = response.context["selection"]
    assert admin_client.post(endpoint, {**data, "post": "yes", "selection": token + "x"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    confirmed = admin_client.post(
        endpoint,
        {**data, "post": "yes", "selection": token, "_selected_action": [str(outside.pk)]},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert confirmed.status_code == 302
    assert Snapshot.objects.filter(status="deleting").count() == 14272
    assert Snapshot.objects.filter(pk__in=[new.pk, outside.pk], status="sealed").count() == 2
    assert ArchiveResult.objects.count() == 3000
    print(f"Preview 14273 rows: {elapsed:.3f}s, {len(response.content)} bytes, {len(captured_queries)} SQL queries")


def test_domains_fallback_posts_frozen_selection_to_native_action(admin_client, crawl):
    selected = Snapshot.objects.create(crawl=crawl, url="https://fallback-fixture.test/selected")
    response = admin_client.post("/admin/domains/actions/", {"delete_domain": "fallback-fixture.test"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    action = response.context["confirmation_url"]
    assert action.startswith("/admin/core/snapshot/?")
    new = Snapshot.objects.create(crawl=crawl, url="https://fallback-fixture.test/new")
    confirmed = admin_client.post(
        action,
        {
            "action": "delete_selected",
            "post": "yes",
            "select_across": "1",
            "_selected_action": str(selected.pk),
            "selection": response.context["selection"],
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert confirmed.status_code == 302
    selected.refresh_from_db()
    new.refresh_from_db()
    assert selected.status == "deleting"
    assert new.status != "deleting"


def test_confirmation_is_user_scope_bound_and_csrf_protected(admin_client, admin_user, crawl):
    from django.test import Client

    selected = Snapshot.objects.create(crawl=crawl, url="https://bound-fixture.test/")
    endpoint = "/admin/core/snapshot/?domain=bound-fixture.test"
    data = {"action": "delete_selected", "select_across": "1", "_selected_action": str(selected.pk)}
    response = admin_client.post(endpoint, data, HTTP_HOST=ADMIN_TEST_HOST)
    confirmed = {**data, "post": "yes", "selection": response.context["selection"]}
    assert admin_client.post("/admin/core/snapshot/", confirmed, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    other = admin_user.__class__.objects.create_superuser(username="otherdeleter", password="test")
    admin_client.force_login(other)
    assert admin_client.post(endpoint, confirmed, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    assert csrf_client.post(endpoint, confirmed, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    selected.refresh_from_db()
    assert selected.status != "deleting"


def test_native_collector_baseline(admin_user, crawl):
    from django.contrib import admin
    from django.test import RequestFactory
    from archivebox.core.admin_snapshots import SnapshotAdmin

    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(crawl=crawl, url=f"https://collector-fixture.test/{i}", timestamp=str(1810000000 + i), status="sealed")
            for i in range(2000)
        ],
    )
    ArchiveResult.objects.bulk_create(
        [ArchiveResult(snapshot=s, plugin="dom", status="succeeded", output_str="dom/output.html") for s in rows],
    )
    request = RequestFactory().post("/admin/core/snapshot/")
    request.user = admin_user
    modeladmin = SnapshotAdmin(Snapshot, admin.site)
    started = time.monotonic()
    with CaptureQueriesContext(connection) as queries:
        objects, counts, permissions, protected = modeladmin.get_deleted_objects(Snapshot.objects.filter(crawl=crawl), request)
    elapsed = time.monotonic() - started
    assert counts[str(Snapshot._meta.verbose_name_plural)] == 2000
    assert not permissions and not protected
    assert objects
    print(
        f"Native collector baseline2000 snapshots+2000 outputs: {elapsed:.3f}s, {len(queries)} queries, {len(str(objects))} serialized chars",
    )


def test_staff_related_delete_permission_is_not_bypassed(client, admin_user, crawl):
    from django.contrib.auth.models import Permission

    staff = admin_user.__class__.objects.create_user(username="staffdeleter", password="test", is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="core", codename__in=["view_snapshot", "delete_snapshot"]),
    )
    selected = Snapshot.objects.create(crawl=crawl, url="https://staff-fixture.test/")
    ArchiveResult.objects.create(snapshot=selected, plugin="dom", status="succeeded")
    client.force_login(staff)
    endpoint = "/admin/core/snapshot/"
    data = {"action": "delete_selected", "_selected_action": str(selected.pk)}
    preview = client.post(endpoint, data, HTTP_HOST=ADMIN_TEST_HOST)
    assert preview.status_code == 200
    assert preview.context["perms_lacking"]
    assert client.post(endpoint, {**data, "post": "yes"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    selected.refresh_from_db()
    assert selected.status != "deleting"
