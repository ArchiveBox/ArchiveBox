"""Whole-site cloning through real forms, queue rows and crawler boundaries."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def clone_data(**overrides):
    return {
        "url": "https://news.ycombinator.com/",
        "max_depth": "2",
        "max_urls": "100",
        "concurrency": "2",
        "timeout_minutes": "60",
        "permissions": "private",
        "url_filters_only_new": "on",
        **overrides,
    }


def test_siteclone_form_creates_bounded_crawl(admin_client):
    from archivebox.crawls.models import Crawl

    response = admin_client.post(
        "/admin/domains/",
        clone_data(url_filters_denylist=r"/(?:login|logout)(?:/|\?|$)"),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.urls.splitlines() == ["https://news.ycombinator.com/", "https://news.ycombinator.com/sitemap.xml"]
    assert crawl.label == "news.ycombinator.com"
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
    assert response["Location"] == crawl.admin_change_url
    page = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert page.context["original"].pk == crawl.pk
    assert page.context["adminform"].form["urls"].value() == crawl.urls
    assert page.content.count(b'id="progress-monitor"') == 1


def test_siteclone_subdomains_and_pause_resume(admin_client):
    from archivebox.crawls.models import Crawl

    response = admin_client.post("/admin/domains/", clone_data(include_subdomains="on"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.url_passes_filters("https://sub.news.ycombinator.com/article")
    assert not crawl.url_passes_filters("https://news.ycombinator.com.example.com/")
    for action, status in (("pause", "paused"), ("resume", "queued")):
        assert admin_client.get(f"/admin/domains/{crawl.pk}/{action}/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
        result = admin_client.post(f"/admin/domains/{crawl.pk}/{action}/", HTTP_HOST=ADMIN_TEST_HOST)
        assert result.status_code == 302
        crawl.refresh_from_db()
        assert crawl.status == status


def test_siteclone_preserves_persona_regex_flags(admin_client):
    from archivebox.config.common import get_config
    from archivebox.personas.models import Persona
    from archivebox.crawls.models import Crawl

    persona = Persona.objects.create(name="Case-insensitive exclusions", config={"URL_DENYLIST": r"(?i)/private(?:/|$)"})
    response = admin_client.post(
        "/admin/domains/",
        clone_data(persona=str(persona.pk), url_filters_denylist=r"/(?:login|logout)(?:/|\?|$)"),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert get_config(crawl=crawl).URL_DENYLIST_PTN is not None
    assert not crawl.url_passes_filters("https://news.ycombinator.com/PRIVATE/")
    assert not crawl.url_passes_filters("https://news.ycombinator.com/login")
    assert crawl.url_passes_filters("https://news.ycombinator.com/public")


def test_siteclone_explicit_port_and_literal_path_boundary(admin_client):
    from archivebox.crawls.models import Crawl

    response = admin_client.post(
        "/admin/domains/",
        clone_data(url="https://news.ycombinator.com:8443/", url_filters_denylist=r"/a\.b\+\(draft\)(?:/|\?|$)", url_filters_only_new=""),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert type(crawl.config["CRAWL_MAX_URLS"]) is int
    assert type(crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"]) is int
    assert type(crawl.config["CRAWL_TIMEOUT"]) is int
    assert crawl.config["ONLY_NEW"] is False
    assert crawl.url_passes_filters("https://news.ycombinator.com:8443/public")
    assert crawl.url_passes_filters("https://news.ycombinator.com:8443/axb+draft")
    for url in (
        "https://news.ycombinator.com:8443/a.b+(draft)",
        "https://news.ycombinator.com:8443/a.b+(draft)/child",
        "https://news.ycombinator.com:84430/public",
        "https://news.ycombinator.com/public",
        "https://news.ycombinator.com.evil.example:8443/public",
    ):
        assert not crawl.url_passes_filters(url), url


def test_recurring_clone_preserves_exact_scope_in_native_scheduler(admin_client, admin_user):
    from archivebox.config.common import get_config
    from archivebox.crawls.models import CrawlSchedule
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(name="Site capture", config={"PLUGINS": "wget,title"})

    response = admin_client.post(
        "/admin/domains/",
        clone_data(
            schedule="daily",
            url_filters_denylist=r"/login(?:/|\?|$)",
            max_urls="5",
            max_depth="1",
            timeout_minutes="30",
            tags="news",
            persona=str(persona.pk),
        ),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    original = Crawl.objects.get()
    schedule = CrawlSchedule.objects.get(template=original)
    assert schedule.schedule == "0 0 * * *" and schedule.is_enabled
    assert schedule.config["CRAWL_MAX_URLS"] == 5
    assert schedule.config["CRAWL_TIMEOUT"] == 1800
    assert schedule.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 2
    assert "PLUGINS" not in schedule.config
    assert get_config(crawl=original).PLUGINS == "wget,title"
    assert schedule.config["PERMISSIONS"] == "private"
    assert schedule.config["ONLY_NEW"] is True
    assert "CHROME_ARGS" not in schedule.config
    recurring = schedule.enqueue(queued_at=schedule.next_run_at)
    assert recurring.status == "queued" and recurring.max_depth == 1
    assert recurring.urls == original.urls and recurring.persona_id == original.persona_id
    assert get_config(crawl=recurring).PLUGINS == "wget,title"
    assert recurring.tags_str == "news,site-clone" and recurring.created_by == admin_user
    assert recurring.config["CRAWL_MAX_URLS"] == 5
    assert recurring.url_passes_filters("https://news.ycombinator.com/newest")
    assert not recurring.url_passes_filters("https://news.ycombinator.com/login")
    assert not recurring.url_passes_filters("https://outside.example/")
    assert response["Location"] == original.admin_change_url
    page = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert page.context["original"].schedule_id == schedule.pk


@pytest.mark.parametrize("schedule", ["not a schedule", "0 0 31 2 *"])
def test_invalid_clone_schedule_queues_nothing(admin_client, schedule):
    from archivebox.crawls.models import Crawl, CrawlSchedule

    response = admin_client.post("/admin/domains/", clone_data(schedule=schedule), HTTP_HOST=ADMIN_TEST_HOST)
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
        {"url_filters_allowlist": "[invalid"},
        {"url_filters_denylist": "[invalid"},
    ],
)
def test_invalid_clone_does_not_queue_work(admin_client, overrides):
    from archivebox.crawls.models import Crawl

    response = admin_client.post("/admin/domains/", clone_data(**overrides), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not Crawl.objects.exists()


def test_siteclone_requires_superuser(client, django_user_model):
    assert client.get("/admin/domains/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    user = django_user_model.objects.create_user("clone-staff", password="test", is_staff=True)
    client.force_login(user)
    assert client.post("/admin/domains/", clone_data(), HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_siteclone_native_filters_preserve_explicit_scope_and_path_boundaries(admin_client):
    from archivebox.crawls.models import Crawl

    response = admin_client.post(
        "/admin/domains/",
        clone_data(
            url="https://news.ycombinator.com/docs/",
            url_filters_subpaths_only="1",
            url_filters_allowlist=r"(?i)^https?://news\.ycombinator\.com/docs/.*story",
            url_filters_denylist=r"(?i)private",
        ),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.config["URL_ALLOWLIST"] == r"(?i)^https?://news\.ycombinator\.com/docs/.*story"
    assert crawl.url_passes_filters("https://news.ycombinator.com/docs/STORY")
    for url in (
        "https://news.ycombinator.com/docs/PRIVATE-story",
        "https://news.ycombinator.com/docstory",
        "https://news.ycombinator.com/outside/story",
        "https://news.ycombinator.com.evil.example/docs/story",
        "https://outside.example/docs/story",
    ):
        assert not crawl.url_passes_filters(url), url
