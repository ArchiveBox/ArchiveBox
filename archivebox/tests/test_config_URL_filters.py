"""Tests for URL_ALLOWLIST and URL_DENYLIST behavior."""

import pytest

from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db


def test_create_snapshots_from_urls_respects_url_allowlist_and_denylist(admin_user):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://example.com/root",
                "https://static.example.com/app.js",
                "https://other.test/page",
            ],
        ),
        created_by=admin_user,
        config={
            "URL_ALLOWLIST": "example.com",
            "URL_DENYLIST": "static.example.com",
        },
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == ["https://example.com/root"]


def test_url_filter_regex_lists_preserve_commas_and_split_on_newlines_only(admin_user):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://example.com/root",
                "https://example.com/path,with,commas",
                "https://other.test/page",
            ],
        ),
        created_by=admin_user,
        config={
            "URL_ALLOWLIST": r"^https://example\.com/(root|path,with,commas)$" + "\n" + r"^https://other\.test/page$",
            "URL_DENYLIST": r"^https://example\.com/path,with,commas$",
        },
    )

    assert crawl.get_url_allowlist(use_effective_config=False) == [
        r"^https://example\.com/(root|path,with,commas)$",
        r"^https://other\.test/page$",
    ]
    assert crawl.get_url_denylist(use_effective_config=False) == [
        r"^https://example\.com/path,with,commas$",
    ]

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == [
        "https://example.com/root",
        "https://other.test/page",
    ]
