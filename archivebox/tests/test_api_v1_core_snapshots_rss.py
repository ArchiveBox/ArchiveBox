from datetime import datetime
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.utils import timezone


pytestmark = pytest.mark.django_db


User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:5797"


@pytest.fixture
def other_user(db):
    return cast(UserManager, User.objects).create_user(
        username="rssother",
        email="rssother@test.com",
        password="testpassword",
    )


def make_snapshot(*, user, url: str, title: str, bookmarked_at: datetime):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls=url, created_by=user)
    snapshot = Snapshot.objects.create(
        url=url,
        title=title,
        crawl=crawl,
        bookmarked_at=bookmarked_at,
    )
    return crawl, snapshot


def test_snapshots_rss_filters_by_user_and_orders_newest_first(client, api_token, api_admin_user, other_user):
    from archivebox.core.models import Tag

    older_at = timezone.make_aware(datetime(2026, 5, 22, 8, 0, 0))
    newer_at = timezone.make_aware(datetime(2026, 5, 23, 8, 0, 0))
    _crawl, older_snapshot = make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-older",
        title="Older & Escaped",
        bookmarked_at=older_at,
    )
    make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-newer",
        title="Newer Snapshot",
        bookmarked_at=newer_at,
    )
    make_snapshot(
        user=other_user,
        url="https://example.com/rss-other-user",
        title="Other User",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 23, 9, 0, 0)),
    )
    older_snapshot.tags.add(Tag.objects.create(name="rss-tag", created_by=api_admin_user))

    response = client.get(
        "/api/v1/core/snapshots.rss",
        {"created_by": api_admin_user.username, "limit": 50, "api_key": api_token.token},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/rss+xml")
    body = response.content.decode()
    assert '<rss version="2.0"' in body
    assert api_token.token not in body
    assert f"created_by={api_admin_user.username}&amp;limit=50" in body
    assert "Newer Snapshot" in body
    assert "Older &amp; Escaped" in body
    assert "Tags: rss-tag" not in body
    assert "<category>rss-tag</category>" in body
    assert "rss-other-user" not in body
    assert body.index("rss-newer") < body.index("rss-older")


def test_snapshots_rss_supports_before_yyyymmdd_and_limit(client, api_token, api_admin_user):
    make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-before-too-new",
        title="Too New",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 24, 8, 0, 0)),
    )
    make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-before-keep-one",
        title="Keep One",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 23, 12, 0, 0)),
    )
    make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-before-keep-two",
        title="Keep Two",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 22, 12, 0, 0)),
    )

    response = client.get(
        "/api/v1/core/snapshots.rss",
        {"created_by": str(api_admin_user.pk), "before": "20260523", "limit": 1, "api_key": api_token.token},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "rss-before-too-new" not in body
    assert "rss-before-keep-one" in body
    assert "rss-before-keep-two" not in body
