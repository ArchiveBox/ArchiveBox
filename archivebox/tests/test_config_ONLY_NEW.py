"""Tests for ONLY_NEW crawl config behavior."""

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db


def test_create_snapshots_from_urls_respects_only_new_exact_url_matches(admin_user):
    existing_crawl = Crawl.objects.create(urls="https://example.com/existing", created_by=admin_user)
    Snapshot.objects.create(
        url="https://example.com/existing",
        crawl=existing_crawl,
        timestamp="1700000000.001",
    )
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://example.com/existing",
                "https://example.com/existing/",
                "https://example.com/fresh",
            ],
        ),
        config={"ONLY_NEW": True},
        created_by=admin_user,
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == [
        "https://example.com/existing/",
        "https://example.com/fresh",
    ]
    assert Snapshot.objects.filter(url="https://example.com/existing").count() == 1


def test_create_snapshots_from_urls_allows_existing_exact_url_when_only_new_false(admin_user):
    existing_crawl = Crawl.objects.create(urls="https://example.com/existing", created_by=admin_user)
    Snapshot.objects.create(
        url="https://example.com/existing",
        crawl=existing_crawl,
        timestamp="1700000000.002",
    )
    crawl = Crawl.objects.create(
        urls="https://example.com/existing",
        config={"ONLY_NEW": False},
        created_by=admin_user,
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == ["https://example.com/existing"]
    assert Snapshot.objects.filter(url="https://example.com/existing").count() == 2


def test_create_discovered_snapshots_respects_only_new_exact_url_matches(admin_user):
    existing_crawl = Crawl.objects.create(urls="https://example.com/existing", created_by=admin_user)
    Snapshot.objects.create(
        url="https://example.com/existing",
        crawl=existing_crawl,
        timestamp="1700000000.003",
    )
    crawl = Crawl.objects.create(
        urls="https://example.com/root",
        max_depth=1,
        config={"ONLY_NEW": True},
        created_by=admin_user,
    )
    parent = crawl.create_snapshots_from_urls()[0]

    created = crawl.create_discovered_snapshots(
        parent,
        [
            {"url": "https://example.com/existing"},
            {"url": "https://example.com/existing/"},
            {"url": "https://example.com/fresh"},
        ],
        depth=1,
    )

    assert [snapshot.url for snapshot in created] == [
        "https://example.com/existing/",
        "https://example.com/fresh",
    ]
    assert Snapshot.objects.filter(url="https://example.com/existing").count() == 1
