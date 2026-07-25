"""Crawl model and admin UI tests."""

import re

import pytest
from django.urls import reverse

from archivebox.core.models import Snapshot
from archivebox.crawls.admin import CrawlAdminForm
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


class TestCrawlScheduleAdmin:
    def test_crawlschedule_change_view_renders_and_saves(self, client, admin_user, crawl):
        from archivebox.crawls.models import CrawlSchedule

        schedule = CrawlSchedule.objects.create(
            label="Nightly crawl",
            notes="",
            schedule="0 0 * * *",
            template=crawl,
            created_by=admin_user,
        )
        client.force_login(admin_user)

        change_url = reverse("admin:crawls_crawlschedule_change", args=[schedule.pk])
        get_response = client.get(change_url, HTTP_HOST=ADMIN_TEST_HOST)

        assert get_response.status_code == 200
        assert b"Schedule Info" in get_response.content
        assert get_response.content.count(b'class="admin-autocomplete"') == 2
        assert b"No Crawls yet..." not in get_response.content
        assert b"No Snapshots yet..." not in get_response.content

        post_response = client.post(
            change_url,
            {
                "label": "Morning crawl",
                "notes": "updated",
                "schedule": "0 8 * * *",
                "template": str(crawl.pk),
                "created_by": str(admin_user.pk),
                "_save": "Save",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert post_response.status_code == 302
        schedule.refresh_from_db()
        assert schedule.label == "Morning crawl"
        assert schedule.notes == "updated"
        assert schedule.schedule == "0 8 * * *"
        assert schedule.template_id == crawl.pk
        assert schedule.created_by_id == admin_user.pk

    def test_crawlschedule_changelist_renders_snapshot_counts(self, client, admin_user, crawl, snapshot):
        from archivebox.crawls.models import CrawlSchedule

        schedule = CrawlSchedule.objects.create(
            label="Daily crawl",
            notes="",
            schedule="0 0 * * *",
            template=crawl,
            created_by=admin_user,
        )
        crawl.schedule = schedule
        crawl.save(update_fields=["schedule"])
        snapshot.crawl = crawl
        snapshot.save(update_fields=["crawl"])

        client.force_login(admin_user)
        url = reverse("admin:crawls_crawlschedule_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Daily crawl" in response.content


def test_crawl_admin_change_view_renders_tag_editor_widget(admin_client, crawl):
    response = admin_client.get(
        reverse("admin:crawls_crawl_change", args=[crawl.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert b'name="tags_editor"' in response.content
    assert b"tag-editor-container" in response.content
    assert b"alpha" in response.content
    assert b"beta" in response.content


def test_crawl_admin_recrawl_object_action_is_post_only(admin_client, crawl):
    action_url = reverse("admin:crawls_crawl_actions", kwargs={"pk": crawl.pk, "tool": "recrawl"})

    change_response = admin_client.get(reverse("admin:crawls_crawl_change", args=[crawl.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert change_response.status_code == 200
    assert b'<form method="post"' in change_response.content
    assert action_url.encode() in change_response.content

    before_count = Crawl.objects.count()
    get_response = admin_client.get(action_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert get_response.status_code == 405
    assert Crawl.objects.count() == before_count

    post_response = admin_client.post(action_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert post_response.status_code == 302
    assert Crawl.objects.count() == before_count + 1


def test_crawl_admin_add_view_renders_url_filter_alias_fields(admin_client):
    response = admin_client.get(
        reverse("admin:crawls_crawl_add"),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert b'name="url_filters_allowlist"' in response.content
    assert b'name="url_filters_denylist"' in response.content
    assert b"Same domain only" in response.content
    assert b"Subpaths only" in response.content


def test_crawl_admin_change_view_checks_effective_only_new(client, admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com",
        config={},
        created_by=admin_user,
    )
    client.force_login(admin_user)
    response = client.get(
        reverse("admin:crawls_crawl_change", args=[crawl.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert b"Effective ONLY_NEW" not in response.content
    assert b'id="id_url_filters_only_new" name="url_filters_only_new" value="1" checked' in response.content


def test_crawl_admin_change_view_derives_url_filter_shortcut_toggles(client, admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/docs/page.html",
        config={"URL_ALLOWLIST": r"^https?://example\.com/docs/"},
        created_by=admin_user,
    )
    client.force_login(admin_user)
    response = client.get(
        reverse("admin:crawls_crawl_change", args=[crawl.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert b'id="id_url_filters_same_domain_only" name="url_filters_same_domain_only" value="1" checked' in response.content
    assert b'id="id_url_filters_subpaths_only" name="url_filters_subpaths_only" value="1" checked' in response.content


def test_admin_change_toolbar_uses_single_save_continue_button(admin_client, crawl):
    response = admin_client.get(
        reverse("admin:crawls_crawl_change", args=[crawl.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    toolbars = re.findall(
        r'<div class="archivebox-toolbar".*?<div class="ab-toolbar-spacer"></div>',
        response.content.decode(),
        flags=re.DOTALL,
    )
    assert toolbars
    for toolbar in toolbars:
        assert 'name="_save"' not in toolbar
        assert 'name="_addanother"' not in toolbar
        assert 'value="Save and continue editing"' not in toolbar
        assert toolbar.count('name="_continue"') == 1
        assert "Save</button>" in toolbar
    assert '<div class="submit-row">' not in response.content.decode()


def test_admin_add_toolbar_hides_save_and_add_another(admin_client):
    response = admin_client.get(
        reverse("admin:crawls_crawl_add"),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    toolbars = re.findall(
        r'<div class="archivebox-toolbar".*?<div class="ab-toolbar-spacer"></div>',
        response.content.decode(),
        flags=re.DOTALL,
    )
    assert toolbars
    for toolbar in toolbars:
        assert 'name="_addanother"' not in toolbar
        assert 'name="_saveasnew"' not in toolbar
        assert toolbar.count('type="submit"') == 1
    assert '<div class="submit-row">' not in response.content.decode()


def test_crawl_schedule_admin_add_redirects_to_add_page_schedule_field(admin_client):
    response = admin_client.get(reverse("admin:crawls_crawlschedule_add"), HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 302
    assert response["Location"] == "/add/#schedule"


def test_crawl_admin_form_saves_tags_editor_to_tags_str(crawl, admin_user):
    form = CrawlAdminForm(
        data={
            "created_at": crawl.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "urls": crawl.urls,
            "config": '{"CRAWL_MAX_URLS": 3, "CRAWL_MAX_SIZE": 47185920, "CRAWL_TIMEOUT": 120, "SNAPSHOT_MAX_SIZE": 5242880}',
            "max_depth": "0",
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
    assert updated.config["CRAWL_MAX_URLS"] == 3
    assert updated.config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert updated.config["CRAWL_TIMEOUT"] == 120
    assert updated.config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024
    assert updated.config["URL_ALLOWLIST"] == "example.com\n*.example.com"
    assert updated.config["URL_DENYLIST"] == "static.example.com"


def test_crawl_admin_resume_action_updates_only_status(client, admin_user, crawl):
    crawl.status = Crawl.StatusChoices.SEALED
    crawl.retry_at = None
    crawl.notes = "unsaved-change-guard"
    crawl.save(update_fields=["status", "retry_at", "notes", "modified_at"])

    client.force_login(admin_user)
    response = client.post(
        reverse("admin:crawls_crawl_changelist"),
        data={
            "action": "resume_selected_crawls",
            "_selected_action": str(crawl.pk),
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is not None
    assert crawl.notes == "unsaved-change-guard"


def test_crawl_admin_pause_action_updates_only_crawl_scheduler_row(client, admin_user, crawl):
    snapshots = crawl.create_snapshots_from_urls()
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:crawls_crawl_changelist"),
        data={
            "action": "pause_selected_crawls",
            "_selected_action": str(crawl.pk),
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.PAUSED
    assert list(Snapshot.objects.filter(pk__in=[snapshot.pk for snapshot in snapshots]).values_list("status", flat=True)) == [
        Snapshot.StatusChoices.QUEUED,
        Snapshot.StatusChoices.QUEUED,
    ]


@pytest.mark.django_db(transaction=True)
def test_crawl_tag_changes_sync_existing_snapshot_tags(crawl):
    snapshots = crawl.create_snapshots_from_urls()
    snapshots[0].save_tags(["alpha", "beta", "keep"])

    crawl.tags_str = "beta,gamma"
    crawl.save(update_fields=["tags_str", "modified_at"])

    assert set(snapshots[0].tags.values_list("name", flat=True)) == {"beta", "gamma", "keep"}
    assert set(snapshots[1].tags.values_list("name", flat=True)) == {"beta", "gamma"}


@pytest.mark.django_db(transaction=True)
def test_create_snapshots_from_urls_uses_current_crawl_tags_for_stale_crawl_instance(crawl):
    crawl.create_snapshots_from_urls()
    fresh_crawl = Crawl.objects.get(pk=crawl.pk)
    fresh_crawl.tags_str = "midcrawl"
    fresh_crawl.save(update_fields=["tags_str", "modified_at"])

    crawl.urls = f"{crawl.urls}\nhttps://example.net/new"
    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == ["https://example.net/new"]
    assert set(created[0].tags.values_list("name", flat=True)) == {"midcrawl"}


@pytest.mark.django_db(transaction=True)
def test_discovered_snapshots_inherit_current_crawl_tags(crawl):
    crawl.max_depth = 1
    crawl.save(update_fields=["max_depth", "modified_at"])
    parent_snapshot = crawl.create_snapshots_from_urls()[0]
    crawl.tags_str = "midcrawl"
    crawl.save(update_fields=["tags_str", "modified_at"])

    created = crawl.create_discovered_snapshots(
        parent_snapshot,
        [{"url": "https://example.com/child", "tags": "discovered"}],
        depth=1,
    )

    assert [snapshot.url for snapshot in created] == ["https://example.com/child"]
    assert set(created[0].tags.values_list("name", flat=True)) == {"midcrawl", "discovered"}


def test_crawl_admin_delete_snapshot_action_removes_snapshot_and_url(client, admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/remove-me",
        created_by=admin_user,
    )
    snapshot = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/remove-me",
    )

    client.force_login(admin_user)
    response = client.post(
        reverse("admin:crawls_crawl_snapshot_delete", args=[crawl.pk, snapshot.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert not Snapshot.objects.filter(pk=snapshot.pk).exists()

    crawl.refresh_from_db()
    assert "https://example.com/remove-me" not in crawl.urls


def test_crawl_admin_exclude_domain_action_prunes_urls_and_pending_snapshots(client, admin_user):
    crawl = Crawl.objects.create(
        urls=("https://cdn.example.com/asset.js\nhttps://cdn.example.com/second.js\nhttps://example.com/root"),
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

    client.force_login(admin_user)
    response = client.post(
        reverse("admin:crawls_crawl_snapshot_exclude_domain", args=[crawl.pk, queued_snapshot.pk]),
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["domain"] == "cdn.example.com"

    crawl.refresh_from_db()
    assert "cdn.example.com" in crawl.get_url_denylist(use_effective_config=False)
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


def test_create_snapshots_from_urls_skips_invalid_and_archivebox_internal_urls(admin_user):
    crawl = Crawl.objects.create(
        urls=("https://example.com/root\nhttp://127.0.0.1:8765/page-001.html\nnot-a-url\nhttp://admin.archivebox.localhost:8000/admin/"),
        created_by=admin_user,
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == [
        "https://example.com/root",
        "http://127.0.0.1:8765/page-001.html",
    ]
    assert list(crawl.snapshot_set.order_by("created_at").values_list("url", flat=True)) == [
        "https://example.com/root",
        "http://127.0.0.1:8765/page-001.html",
    ]


def test_crawl_stop_reason_reports_no_viable_urls_for_sealed_empty_crawl(admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/already-known",
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
        created_by=admin_user,
    )

    assert crawl.stop_reason() == "no_viable_urls"


def test_crawl_stop_reason_reports_done_for_sealed_crawl_with_all_snapshots_sealed(admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/done",
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
        created_by=admin_user,
    )
    Snapshot.objects.create(
        url="https://example.com/done",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        timestamp="1700000000.010",
    )

    assert crawl.stop_reason() == "done"


def test_crawl_stop_reason_reports_paused_for_paused_crawl(admin_user):
    crawl = Crawl.objects.create(
        urls="https://example.com/paused",
        status=Crawl.StatusChoices.PAUSED,
        created_by=admin_user,
    )

    assert crawl.stop_reason() == "paused"
