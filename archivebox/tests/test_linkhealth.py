"""Real URL probes change normal snapshot tags without separate health models."""

import io
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from django.core.management import call_command, CommandError

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


def test_real_check_tags_missing_urls_and_removes_tag_on_recovery(admin_user, health_site):
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.service import check_snapshots

    base, root = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    good = Snapshot.objects.create(url=f"{base}/article.html", crawl=crawl)
    missing = Snapshot.objects.create(url=f"{base}/restored.html", crawl=crawl)
    manual = Tag.get_or_create_by_name("manual")[0]
    good.add_tag_ids([manual.pk])
    missing.add_tag_ids([manual.pk])
    output = io.StringIO()
    check_snapshots(Snapshot.objects.filter(crawl=crawl), output)
    assert set(missing.tags.values_list("name", flat=True)) == {"manual", "offline"}
    assert set(good.tags.values_list("name", flat=True)) == {"manual"}
    assert json.loads(output.getvalue().splitlines()[-1])["counts"] == {"reachable": 1, "offline": 1}
    (root / "restored.html").write_text("<title>Restored page</title>")
    call_command("linkhealth", user=admin_user.pk, snapshot=[str(missing.pk)], stdout=io.StringIO())
    assert set(missing.tags.values_list("name", flat=True)) == {"manual"}
    assert Snapshot.objects.count() == 2


def test_command_reuses_folder_and_search_filters(admin_user, health_site):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    base, _ = health_site
    folder = Folder.objects.create(name="Check this folder")
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    selected = Snapshot.objects.create(url=f"{base}/missing-a.html", title="Selected", crawl=crawl, folder=folder)
    other = Snapshot.objects.create(url=f"{base}/missing-b.html", title="Other", crawl=crawl)
    output = io.StringIO()
    call_command("linkhealth", user=admin_user.pk, query=f"folder={folder.pk}&q=Selected&search_mode=meta", stdout=output)
    assert selected.tags.filter(name="offline").exists()
    assert not other.tags.filter(name="offline").exists()
    assert json.loads(output.getvalue().splitlines()[-1])["checked"] == 1


def test_anonymous_unsupported_checks_preserve_existing_offline_tag(admin_user, health_site):
    import requests
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.linkhealth.service import check_snapshot

    base, _ = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    snapshot = Snapshot.objects.create(url=base.replace("http://", "http://private:secret@") + "/article.html", crawl=crawl)
    snapshot.add_tag_ids([Tag.get_or_create_by_name(name)[0].pk for name in ("offline", "manual")])
    with requests.Session() as session:
        result = check_snapshot(snapshot, session)
    assert result["status"] == "unsupported"
    assert set(snapshot.tags.values_list("name", flat=True)) == {"offline", "manual"}


def test_check_page_uses_native_tags_and_rejects_invalid_selection(admin_client, admin_user, health_site):
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process

    base, _ = health_site
    crawl = Crawl.objects.create(urls=base, created_by=admin_user)
    snapshot = Snapshot.objects.create(url=f"{base}/article.html", crawl=crawl)
    snapshot.add_tag_ids([Tag.get_or_create_by_name("offline")[0].pk])
    response = admin_client.get("/admin/link-health/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"1 tagged offline" in response.content
    assert b"Duplicate" not in response.content
    assert admin_client.get("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    for selected in ([], ["invalid"], ["0" * 32]):
        response = admin_client.post("/admin/link-health/scan/", {"scope": "selected", "snapshot_ids": selected}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 400
    assert not Process.objects.filter(worker_type="link-check").exists()


def test_checks_require_superuser(client, django_user_model):
    user = django_user_model.objects.create_user("link-viewer", password="test", is_staff=True)
    client.force_login(user)
    assert client.get("/admin/link-health/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    assert client.post("/admin/link-health/scan/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    with pytest.raises(CommandError, match="superuser"):
        call_command("linkhealth", user=user.pk)


def test_scan_launcher_rejects_option_as_snapshot_id_before_starting_process(admin_user):
    from archivebox.config import CONSTANTS
    from archivebox.linkhealth.service import launch_check
    from archivebox.machine.models import Process

    directory = CONSTANTS.DATA_DIR / "logs" / "link-checks"
    prior_directories = set(directory.iterdir()) if directory.exists() else set()
    prior_processes = Process.objects.filter(worker_type="link-check").count()
    process = None
    try:
        with pytest.raises(ValueError):
            process = launch_check(user_id=admin_user.pk, snapshot_ids=["--help"])
    finally:
        if process is not None:
            process.kill()
    assert Process.objects.filter(worker_type="link-check").count() == prior_processes
    assert (set(directory.iterdir()) if directory.exists() else set()) == prior_directories


def test_check_filters_preserve_inherited_native_scope(admin_client, admin_user):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    selected = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    other = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    Snapshot.objects.create(url=selected.urls, crawl=selected, title="Selected article")
    Snapshot.objects.create(url=other.urls, crawl=other, title="Other article")
    response = admin_client.get(
        "/admin/link-health/",
        {"crawl__id__exact": str(selected.pk), "search_mode": "meta"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["count"] == 1
    assert f'name="crawl__id__exact" value="{selected.pk}"'.encode() in response.content
    assert b'name="search_mode" value="meta"' in response.content
    assert set(response.context["inherited_filters"]) == {("crawl__id__exact", str(selected.pk)), ("search_mode", "meta")}
    updated = dict(response.context["inherited_filters"], q="Selected", url__icontains="ycombinator")
    response = admin_client.get("/admin/link-health/", updated, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200 and response.context["count"] == 1
    assert {str(item.pk) for item in response.context["snapshots"]} == {str(Snapshot.objects.get(crawl=selected).pk)}
