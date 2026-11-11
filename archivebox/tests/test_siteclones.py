"""Whole-site cloning through real forms, queue rows and crawler boundaries."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def clone_data(**overrides):
    return {
        "url": "https://news.ycombinator.com/",
        "name": "Hacker News",
        "max_depth": "2",
        "max_urls": "100",
        "concurrency": "2",
        "timeout_minutes": "60",
        "permissions": "private",
        "only_new": "on",
        **overrides,
    }


def test_siteclone_form_creates_bounded_crawl(admin_client):
    from archivebox.siteclones.models import SiteClone

    response = admin_client.post("/admin/site-clones/", clone_data(exclude_paths="/login\n/logout"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    clone = SiteClone.objects.select_related("crawl").get()
    crawl = clone.crawl
    assert crawl.urls == "https://news.ycombinator.com/"
    assert crawl.max_depth == 2
    assert crawl.config["CRAWL_MAX_URLS"] == 100
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 2
    assert crawl.config["CRAWL_TIMEOUT"] == 3600
    assert crawl.permissions == "private"
    from archivebox.config.common import get_config

    assert get_config(crawl=crawl).URL_DENYLIST_PTN is not None
    assert crawl.status == "queued"
    assert crawl.url_passes_filters("https://news.ycombinator.com/item?id=1")
    for url in (
        "https://news.ycombinator.com.evil.example/",
        "https://sub.news.ycombinator.com/",
        "https://example.com/",
        "https://news.ycombinator.com/login",
    ):
        assert not crawl.url_passes_filters(url), url
    detail = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert detail.status_code == 200
    assert b"Hacker News" in detail.content
    assert b"100" in detail.content
    assert b"bounded crawl" in detail.content
    assert detail.content.count(b'id="progress-monitor"') == 1


def test_siteclone_subdomains_and_pause_resume(admin_client):
    from archivebox.siteclones.models import SiteClone

    response = admin_client.post("/admin/site-clones/", clone_data(include_subdomains="on"), HTTP_HOST=ADMIN_TEST_HOST)
    clone = SiteClone.objects.select_related("crawl").get()
    assert clone.crawl.url_passes_filters("https://sub.news.ycombinator.com/article")
    assert not clone.crawl.url_passes_filters("https://news.ycombinator.com.example.com/")
    for action, status in (("pause", "paused"), ("resume", "queued")):
        assert admin_client.get(f"{response['Location']}{action}/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
        result = admin_client.post(f"{response['Location']}{action}/", HTTP_HOST=ADMIN_TEST_HOST)
        assert result.status_code == 302
        clone.crawl.refresh_from_db()
        assert clone.crawl.status == status


def test_siteclone_preserves_persona_regex_flags(admin_client):
    from archivebox.config.common import get_config
    from archivebox.personas.models import Persona
    from archivebox.siteclones.models import SiteClone

    persona = Persona.objects.create(name="Case-insensitive exclusions", config={"URL_DENYLIST": r"(?i)/private(?:/|$)"})
    response = admin_client.post(
        "/admin/site-clones/",
        clone_data(persona=str(persona.pk), exclude_paths="/login\n/logout"),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    crawl = SiteClone.objects.get().crawl
    assert get_config(crawl=crawl).URL_DENYLIST_PTN is not None
    assert not crawl.url_passes_filters("https://news.ycombinator.com/PRIVATE/")
    assert not crawl.url_passes_filters("https://news.ycombinator.com/login")
    assert crawl.url_passes_filters("https://news.ycombinator.com/public")


def test_recurring_clone_preserves_exact_scope_in_native_scheduler(admin_client, admin_user):
    from archivebox.crawls.models import CrawlSchedule
    from archivebox.siteclones.models import SiteClone

    response = admin_client.post(
        "/admin/site-clones/",
        clone_data(
            schedule="daily",
            exclude_paths="/login",
            max_urls="5",
            max_depth="1",
            timeout_minutes="30",
            tags="news",
            plugins=["wget", "title"],
        ),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    original = SiteClone.objects.get().crawl
    schedule = CrawlSchedule.objects.get(template=original)
    assert schedule.schedule == "0 0 * * *" and schedule.is_enabled
    assert schedule.config["CRAWL_MAX_URLS"] == 5
    assert schedule.config["CRAWL_TIMEOUT"] == 1800
    assert schedule.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 2
    assert schedule.config["PLUGINS"] == "wget,title"
    assert schedule.config["PERMISSIONS"] == "private"
    assert schedule.config["ONLY_NEW"] is True
    assert "CHROME_ARGS" not in schedule.config
    recurring = schedule.enqueue(queued_at=schedule.next_run_at)
    assert recurring.status == "queued" and recurring.max_depth == 1
    assert recurring.urls == original.urls and recurring.persona_id == original.persona_id
    assert recurring.tags_str == "news" and recurring.created_by == admin_user
    assert recurring.config["CRAWL_MAX_URLS"] == 5
    assert recurring.url_passes_filters("https://news.ycombinator.com/newest")
    assert not recurring.url_passes_filters("https://news.ycombinator.com/login")
    assert not recurring.url_passes_filters("https://outside.example/")
    detail = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert detail.status_code == 200
    assert b"Next run" in detail.content and b"Manage schedule" in detail.content
    assert schedule.admin_change_url.encode() in detail.content


@pytest.mark.parametrize("schedule", ["not a schedule", "0 0 31 2 *"])
def test_invalid_clone_schedule_queues_nothing(admin_client, schedule):
    from archivebox.crawls.models import Crawl, CrawlSchedule

    response = admin_client.post("/admin/site-clones/", clone_data(schedule=schedule), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["form"].errors["schedule"]
    assert not Crawl.objects.exists() and not CrawlSchedule.objects.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com"},
        {"url": "https://user:password@example.com/"},
        {"max_depth": "5"},
        {"max_urls": "0"},
        {"concurrency": "0"},
        {"exclude_paths": "https://other.example/"},
        {"exclude_paths": "/"},
    ],
)
def test_invalid_clone_does_not_queue_work(admin_client, overrides):
    from archivebox.crawls.models import Crawl

    response = admin_client.post("/admin/site-clones/", clone_data(**overrides), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not Crawl.objects.exists()


def test_siteclone_requires_superuser(client, django_user_model):
    assert client.get("/admin/site-clones/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    user = django_user_model.objects.create_user("clone-staff", password="test", is_staff=True)
    client.force_login(user)
    assert client.post("/admin/site-clones/", clone_data(), HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
