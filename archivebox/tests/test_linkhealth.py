"""Link health uses real HTTP, saved files, database rows and admin requests."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def health_site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "article.html").write_text("<title>Real article</title><p>Saved article content.</p>")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", root
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_scan_checks_real_responses_and_preserves_captures(admin_client, admin_user, health_site):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.models import LinkCheck, LinkScan
    from archivebox.linkhealth.service import run_next

    base, _ = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    good = Snapshot.objects.create(url=f"{base}/article.html", crawl=crawl, status="sealed")
    broken = Snapshot.objects.create(url=f"{base}/missing.html", crawl=crawl, status="sealed")
    assert admin_client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    run = LinkScan.objects.get()
    assert run.status == "succeeded" and run.checked == 2
    assert LinkCheck.objects.get(snapshot=good).status == "ok"
    failure = LinkCheck.objects.get(snapshot=broken)
    assert failure.status == "broken" and failure.status_code == 404
    assert Snapshot.objects.count() == 2
    response = admin_client.get("/admin/link-health/", {"status": "broken"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"missing.html" in response.content
    assert b"article.html" not in response.content


def test_review_search_sort_and_retry_one_real_link(admin_client, admin_user, health_site):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.models import LinkCheck, LinkScan
    from archivebox.linkhealth.service import run_next

    base, root = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    good = Snapshot.objects.create(url=f"{base}/article.html", title="Zulu article", crawl=crawl, status="sealed")
    broken = Snapshot.objects.create(url=f"{base}/restored.html", title="Alpha article", crawl=crawl, status="sealed")
    assert admin_client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    response = admin_client.get("/admin/link-health/", {"q": "Alpha", "sort": "title"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert [check.snapshot_id for check in response.context["checks"]] == [broken.pk]
    response = admin_client.get("/admin/link-health/", {"sort": "title"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert [check.snapshot_id for check in response.context["checks"]] == [broken.pk, good.pk]
    unchanged = LinkCheck.objects.get(snapshot=good).checked_at
    (root / "restored.html").write_text("<title>Restored page</title><p>This page is available again.</p>")
    assert admin_client.get(f"/admin/link-health/{broken.pk}/retry/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    assert admin_client.post(f"/admin/link-health/{broken.pk}/retry/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    assert LinkScan.objects.first().checked == 1
    assert LinkCheck.objects.get(snapshot=broken).status == "ok"
    assert LinkCheck.objects.get(snapshot=good).checked_at == unchanged
    assert Snapshot.objects.count() == 2


def test_bulk_recheck_validates_selection_and_checks_only_selected(admin_client, admin_user, health_site, django_user_model):
    from django.test import Client

    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.models import LinkCheck, LinkScan
    from archivebox.linkhealth.service import run_next

    base, _ = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"{base}/article.html#{i}", crawl=crawl, status="sealed") for i in range(3)]
    assert admin_client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    untouched = LinkCheck.objects.get(snapshot=snapshots[2]).checked_at
    path = "/admin/link-health/recheck/"
    assert admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    for selection in ([], ["not-a-snapshot"], ["0" * 32]):
        response = admin_client.post(path, {"snapshot_ids": selection}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 400
        assert not LinkScan.objects.filter(status="queued").exists()
    user = django_user_model.objects.create_user("bulk-health-staff", password="test", is_staff=True)
    client = Client()
    client.force_login(user)
    assert client.post(path, {"snapshot_ids": [str(snapshots[0].pk)]}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    response = admin_client.post(path, {"snapshot_ids": [str(snapshot.pk) for snapshot in snapshots[:2]]}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert run_next()
    assert LinkScan.objects.first().checked == 2
    assert LinkCheck.objects.get(snapshot=snapshots[2]).checked_at == untouched
    assert Snapshot.objects.count() == 3


def test_url_candidates_preserve_query_and_captures(admin_client, admin_user):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.service import normalized_url

    assert normalized_url("https://EXAMPLE.com:443/a#part") == normalized_url("https://example.com/a")
    assert normalized_url("https://example.com/a?id=1") != normalized_url("https://example.com/a?id=2")
    for _ in range(2):
        crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
        Snapshot.objects.create(url="https://example.com/article", crawl=crawl, status="sealed")
    response = admin_client.get("/admin/link-health/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"https://example.com/article" in response.content
    assert b"versions" in response.content
    assert Snapshot.objects.count() == 2


def test_checks_require_superuser_and_post(client, django_user_model):
    assert client.get("/admin/link-health/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    user = django_user_model.objects.create_user("health-staff", password="test", is_staff=True)
    client.force_login(user)
    assert client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_equivalent_urls_are_reviewable_after_real_checks(admin_client, admin_user, health_site):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.service import run_next

    base, _ = health_site
    for suffix in ("", "#paragraph"):
        crawl = Crawl.objects.create(urls=base, created_by=admin_user)
        Snapshot.objects.create(url=f"{base}/article.html{suffix}", crawl=crawl, status="sealed")
    assert admin_client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    response = admin_client.get("/admin/link-health/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Equivalent URLs" in response.content
    assert b"#paragraph" in response.content
    assert Snapshot.objects.count() == 2


def test_health_schedule_and_duplicate_scan_submission(admin_client):
    from archivebox.linkhealth.models import LinkScan, LinkHealthSettings

    assert admin_client.post("/admin/link-health/", {"interval_days": "7"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    policy = LinkHealthSettings.objects.get()
    assert policy.interval_days == 7 and policy.next_scan_at is not None
    assert admin_client.get("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    for _ in range(2):
        assert admin_client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert LinkScan.objects.count() == 1


def test_real_captures_find_identical_saved_content(initialized_archive, health_site):
    import hashlib

    from archivebox.linkhealth.models import LinkCheck, LinkScan
    from archivebox.tests.conftest import run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    base, root = health_site
    original = (root / "article.html").read_bytes()
    (root / "copy.html").write_bytes(original)
    capture = run_archivebox_cmd(
        ["add", "--plugins=wget", f"{base}/article.html", f"{base}/copy.html"],
        cwd=initialized_archive,
        timeout=120,
        default_cli_env=True,
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    scan = run_archivebox_cmd(["manage", "linkhealth", "--scan", "--once"], cwd=initialized_archive, timeout=60, default_cli_env=True)
    assert scan.returncode == 0, scan.stdout + scan.stderr
    with use_archivebox_db(initialized_archive):
        assert LinkScan.objects.get().status == "succeeded"
        assert LinkCheck.objects.count() == 2
        assert set(LinkCheck.objects.values_list("content_hash", flat=True)) == {hashlib.sha256(original).hexdigest()}
        assert set(LinkCheck.objects.values_list("status", flat=True)) == {"ok"}
