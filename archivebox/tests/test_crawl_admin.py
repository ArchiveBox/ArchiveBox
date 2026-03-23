from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.urls import reverse

from archivebox.crawls.admin import CrawlAdminForm
from archivebox.crawls.models import Crawl
from archivebox.core.models import Snapshot


pytestmark = pytest.mark.django_db


User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:8000"


@pytest.fixture
def admin_user(db):
    return cast(UserManager, User.objects).create_superuser(
        username="crawladmin",
        email="crawladmin@test.com",
        password="testpassword",
    )


@pytest.fixture
def crawl(admin_user):
    return Crawl.objects.create(
        urls="https://example.com\nhttps://example.org",
        tags_str="alpha,beta",
        created_by=admin_user,
    )


def test_crawl_admin_change_view_renders_tag_editor_widget(client, admin_user, crawl):
    client.login(username="crawladmin", password="testpassword")

    response = client.get(
        reverse("admin:crawls_crawl_change", args=[crawl.pk]),
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert b'name="tags_editor"' in response.content
    assert b"tag-editor-container" in response.content
    assert b"alpha" in response.content
    assert b"beta" in response.content


def test_crawl_admin_add_view_renders_url_filter_alias_fields(client, admin_user):
    client.login(username="crawladmin", password="testpassword")

    response = client.get(
        reverse("admin:crawls_crawl_add"),
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert b'name="url_filters_allowlist"' in response.content
    assert b'name="url_filters_denylist"' in response.content
    assert b"Same domain only" in response.content


def test_crawl_admin_form_saves_tags_editor_to_tags_str(crawl, admin_user):
    form = CrawlAdminForm(
        data={
            "created_at": crawl.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "urls": crawl.urls,
            "config": "{}",
            "max_depth": "0",
            "max_urls": "3",
            "max_size": str(45 * 1024 * 1024),
            "tags_editor": "alpha, beta, Alpha, gamma",
            "url_filters_allowlist": "example.com\n*.example.com",
            "url_filters_denylist": "static.example.com",
            "persona_id": "",
            "label": "",
            "notes": "",
            "schedule": "",
            "status": crawl.status,
            "retry_at": crawl.retry_at.strftime("%Y-%m-%d %H:%M:%S"),
            "created_by": str(admin_user.pk),
            "num_uses_failed": "0",
            "num_uses_succeeded": "0",
        },
        instance=crawl,
    )

    assert form.is_valid(), form.errors

    updated = form.save()
    updated.refresh_from_db()
    assert updated.tags_str == "alpha,beta,gamma"
    assert updated.max_urls == 3
    assert updated.max_size == 45 * 1024 * 1024
    assert updated.config["MAX_URLS"] == 3
    assert updated.config["MAX_SIZE"] == 45 * 1024 * 1024
    assert updated.config["URL_ALLOWLIST"] == "example.com\n*.example.com"
    assert updated.config["URL_DENYLIST"] == "static.example.com"


def test_crawl_admin_delete_snapshot_action_removes_snapshot_and_url(client, admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/remove-me",
        created_by=admin_user,
    )
    snapshot = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/remove-me",
    )

    client.login(username="crawladmin", password="testpassword")
    response = client.post(
        reverse("admin:crawls_crawl_snapshot_delete", args=[crawl.pk, snapshot.pk]),
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert not Snapshot.objects.filter(pk=snapshot.pk).exists()

    crawl.refresh_from_db()
    assert "https://example.com/remove-me" not in crawl.urls


def test_crawl_admin_exclude_domain_action_prunes_urls_and_pending_snapshots(client, admin_user):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://cdn.example.com/asset.js",
                "https://cdn.example.com/second.js",
                "https://example.com/root",
            ],
        ),
        created_by=admin_user,
    )
    queued_snapshot = Snapshot.objects.create(
        crawl=crawl,
        url="https://cdn.example.com/asset.js",
        status=Snapshot.StatusChoices.QUEUED,
    )
    preserved_snapshot = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/root",
        status=Snapshot.StatusChoices.SEALED,
    )

    client.login(username="crawladmin", password="testpassword")
    response = client.post(
        reverse("admin:crawls_crawl_snapshot_exclude_domain", args=[crawl.pk, queued_snapshot.pk]),
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["domain"] == "cdn.example.com"

    crawl.refresh_from_db()
    assert crawl.get_url_denylist(use_effective_config=False) == ["cdn.example.com"]
    assert "https://cdn.example.com/asset.js" not in crawl.urls
    assert "https://cdn.example.com/second.js" not in crawl.urls
    assert "https://example.com/root" in crawl.urls
    assert not Snapshot.objects.filter(pk=queued_snapshot.pk).exists()
    assert Snapshot.objects.filter(pk=preserved_snapshot.pk).exists()


def test_snapshot_from_json_trims_markdown_suffixes_on_discovered_urls(crawl):
    snapshot = Snapshot.from_json(
        {"url": "https://docs.sweeting.me/s/youtube-favorites)**"},
        overrides={"crawl": crawl},
        queue_for_extraction=False,
    )

    assert snapshot is not None
    assert snapshot.url == "https://docs.sweeting.me/s/youtube-favorites"


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
