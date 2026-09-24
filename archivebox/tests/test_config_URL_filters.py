"""Tests for URL_ALLOWLIST and URL_DENYLIST behavior."""

import pytest

from archivebox.config.common import ArchivingConfig
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db


def test_default_denylist_excludes_hn_actions_from_discovered_snapshots(admin_user):
    crawl = Crawl.objects.create(
        urls="https://news.ycombinator.com/",
        max_depth=1,
        created_by=admin_user,
        config={"URL_DENYLIST": ArchivingConfig.model_fields["URL_DENYLIST"].default},
    )
    parent = crawl.create_snapshots_from_urls()[0]
    blocked = [
        "https://news.ycombinator.com/vote?id=123&how=up&goto=news",
        "https://news.ycombinator.com/vote?id=123&how=down&goto=news",
        "https://news.ycombinator.com/hide?id=123&goto=news",
        "http://news.ycombinator.com/vote",
        "https://news.ycombinator.com/hide/#123",
        "https://example.com/site.css?v=1",
    ]
    allowed = [
        "https://news.ycombinator.com/item?id=123",
        "https://news.ycombinator.com/user?id=example",
        "https://news.ycombinator.com/from?site=example.com",
        "https://news.ycombinator.com/vote-guide",
        "https://news.ycombinator.com/vote/article",
        "https://example.com/vote?id=123",
        "https://news.ycombinator.com.example.org/hide?id=123",
        "https://example.com/article?next=https://news.ycombinator.com/vote?id=123",
    ]

    created = crawl.create_discovered_snapshots(parent, [{"url": url} for url in blocked + allowed], depth=1)

    assert {snapshot.url for snapshot in created} == set(allowed)
    assert set(crawl.snapshot_set.filter(depth=1).values_list("url", flat=True)) == set(allowed)


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
