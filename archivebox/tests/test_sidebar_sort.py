from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client

from archivebox.core.models import Snapshot, SnapshotTag, Tag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine
from archivebox.tests.conftest import ADMIN_TEST_HOST, WEB_TEST_HOST


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["tags", "domains"])
def test_sidebar_order_stays_scoped_and_consistent_across_pages(admin_client, admin_user, monkeypatch, mode):
    monkeypatch.setattr("archivebox.core.sidebar.SIDEBAR_PAGE_SIZE", 2)
    monkeypatch.setattr("archivebox.core.sidebar.DOMAIN_SIDEBAR_PAGE_SIZE", 2)
    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://alpha.com/")
    tags = {name: Tag.objects.create(name=name.title()) for name in ("alpha", "gamma", "zebra", "hidden")}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, (name, host, access) in enumerate(
        [
            ("zebra", "zebra.net", "public"),
            ("zebra", "www.zebra.net", "public"),
            ("zebra", "www.zebra.net", "private"),
            ("alpha", "alpha.com", "public"),
            ("hidden", "hidden.org", "unlisted"),
            ("gamma", "gamma.edu", "public"),
            ("hidden", "hidden.org", "private"),
        ],
    ):
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url=f"https://{host}/{i}",
            timestamp=str(1910000000 + i),
            created_at=start + timedelta(days=i),
            config={"PERMISSIONS": access},
        )
        SnapshotTag.objects.create(snapshot=snapshot, tag=tags[name])

    def get(browser, host, params):
        path = "/public/sidebar/" if host == WEB_TEST_HOST else "/admin/core/snapshot/sidebar/"
        return browser.get(path, {"sidebar": mode, **params}, HTTP_HOST=host)

    def names(body):
        return [row["name"].split(".")[0].casefold() for row in body["choices"]]

    expected = {
        "count": ["zebra", "hidden", "alpha", "gamma"],
        "name": ["alpha", "gamma", "hidden", "zebra"],
        "newest": ["hidden", "gamma", "alpha", "zebra"],
    }
    for sort, ordered in expected.items():
        params = {} if sort == "count" else {"sidebar_sort": sort}
        first = get(admin_client, ADMIN_TEST_HOST, params).json()
        second = get(admin_client, ADMIN_TEST_HOST, {**params, "cursor": first["next"]}).json()
        assert names(first) + names(second) == ordered
        assert second["next"] == ""
        searched = get(admin_client, ADMIN_TEST_HOST, {**params, "sidebar_q": "a"}).json()
        assert names(searched) == [name for name in ordered if "a" in name][:2]

    public = Client()
    admin_first = get(admin_client, ADMIN_TEST_HOST, {"sidebar_sort": "newest"}).json()
    assert get(public, WEB_TEST_HOST, {"sidebar_sort": "newest", "cursor": admin_first["next"]}).status_code == 400
    assert get(admin_client, ADMIN_TEST_HOST, {"sidebar_sort": "name", "cursor": admin_first["next"]}).status_code == 400
    public_first = get(public, WEB_TEST_HOST, {"sidebar_sort": "newest"}).json()
    public_last = get(public, WEB_TEST_HOST, {"sidebar_sort": "newest", "cursor": public_first["next"]}).json()
    assert names(public_first) + names(public_last) == ["gamma", "alpha", "zebra"]

    loaded = admin_client.get("/admin/core/snapshot/", {"sidebar": mode, "sidebar_sort": "newest"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert loaded.status_code == 200
    assert loaded.context["sidebar_sort"] == "newest"
    assert "sidebar_sort" not in str(loaded.context["sidebar_export_urls"])
