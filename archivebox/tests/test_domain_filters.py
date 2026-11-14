"""Site capture options use the native crawl filter and persona semantics."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_site_form_defaults(admin_client):
    response = admin_client.get("/admin/domains/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    form = response.context["form"]
    assert form["max_depth"].value() == 3
    assert form["url_filters"].value() == {"same_domain_only": True, "subpaths_only": False, "only_new": True}


@pytest.mark.parametrize("allowlist", ["", "/newest|/sitemap"])
def test_domain_subpath_scope_allows_seed_sitemap_without_generated_denials(admin_client, allowlist):
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(name="Subpath capture", config={"URL_ALLOWLIST": "", "URL_DENYLIST": ""})
    response = post_site(
        admin_client,
        url="https://news.ycombinator.com/newest",
        url_filters_same_domain_only="on",
        url_filters_subpaths_only="on",
        url_filters_allowlist=allowlist,
        url_filters_denylist="/login",
        persona=str(persona.pk),
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.config["URL_DENYLIST"] == "/login"
    assert all(crawl.url_passes_filters(url) for url in crawl.get_urls_list())
    assert not crawl.url_passes_filters("https://news.ycombinator.com/newest/login")
    if not allowlist:
        for url in (
            "https://outside.example/newest",
            "https://news.ycombinator.com/other",
            "https://news.ycombinator.com/sitemap.xml/other",
        ):
            assert not crawl.url_passes_filters(url), url
    else:
        assert crawl.config["URL_ALLOWLIST"] == allowlist


def test_domain_explicit_sitemap_exclusion_is_preserved(admin_client):
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(name="Explicit exclusions", config={"URL_ALLOWLIST": "", "URL_DENYLIST": ""})
    response = post_site(admin_client, persona=str(persona.pk), url_filters_subpaths_only="on", url_filters_denylist=r"/sitemap\.xml$")
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.config["URL_DENYLIST"] == r"/sitemap\.xml$"
    assert not crawl.url_passes_filters("https://example.com/sitemap.xml")


@pytest.mark.parametrize(
    ("url", "sitemap"),
    [
        ("https://news.ycombinator.com/item?id=1", "https://news.ycombinator.com/sitemap.xml"),
        ("http://news.ycombinator.com/", "https://news.ycombinator.com/sitemap.xml"),
        ("https://news.ycombinator.com/sitemap.xml", "https://news.ycombinator.com/sitemap.xml"),
        ("https://news.ycombinator.com:8443/docs", "https://news.ycombinator.com:8443/sitemap.xml"),
    ],
)
def test_site_seeds_native_crawl_with_sitemap(admin_client, url, sitemap):
    from archivebox.crawls.models import Crawl

    response = post_site(admin_client, url=url)
    assert response.status_code == 302
    assert Crawl.objects.get().urls.splitlines() == list(dict.fromkeys([url, sitemap]))


def test_more_options_prefills_and_saves_native_add_form(admin_client):
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(name="News reader", config={"ONLY_NEW": False})
    values = {
        "url": "https://news.ycombinator.com/\nhttps://news.ycombinator.com/sitemap.xml",
        "tag": "news,reading",
        "persona": persona.name,
        "permissions": "private",
        "depth": "3",
        "max_urls": "125",
        "crawl_timeout": "1800",
        "crawl_max_concurrent_snapshots": "4",
        "schedule": "daily",
        "url_filters_allowlist": "news.ycombinator.com",
        "url_filters_denylist": "/login\n^(?!https?://news\\.ycombinator\\.com(?:/|$))",
        "url_filters_same_domain_only": "1",
        "url_filters_subpaths_only": "0",
        "url_filters_only_new": "1",
    }
    response = admin_client.get("/add/", values, HTTP_HOST="web.archivebox.localhost:5797")
    assert response.status_code == 200
    form = response.context["form"]
    for name, value in values.items():
        if not name.startswith("url_filters_"):
            assert str(form[name].value()) == value, name
    assert form["url_filters"].value() == {
        "allowlist": "news.ycombinator.com",
        "denylist": values["url_filters_denylist"],
        "same_domain_only": True,
        "subpaths_only": False,
        "only_new": True,
    }
    import json

    response = admin_client.post(
        "/add/",
        {**values, "config": json.dumps({"URL_DENYLIST": values["url_filters_denylist"].replace("\n", "")})},
        HTTP_HOST="web.archivebox.localhost:5797",
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.get_urls_list() == values["url"].splitlines()
    assert crawl.persona_id == persona.pk
    assert crawl.tags_str == "news,reading"
    assert crawl.permissions == "private"
    assert crawl.max_depth == 3
    assert crawl.config["CRAWL_MAX_URLS"] == 125
    assert crawl.config["CRAWL_TIMEOUT"] == 1800
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 4
    assert crawl.config["ONLY_NEW"] is True
    assert crawl.config["URL_DENYLIST"] == values["url_filters_denylist"]
    assert not crawl.url_passes_filters("https://news.ycombinator.com/login")
    assert not crawl.url_passes_filters("https://outside.example/")
    assert crawl.url_passes_filters("https://news.ycombinator.com/newest")
    assert CrawlSchedule.objects.get(template=crawl).schedule == values["schedule"]


def post_site(client, **overrides):
    return client.post(
        "/admin/domains/",
        {
            "url": "https://example.com/docs",
            "max_depth": "2",
            "max_urls": "100",
            "concurrency": "2",
            "timeout_minutes": "60",
            "permissions": "private",
            **overrides,
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )


def test_site_filters_preserve_selected_persona_defaults(admin_client):
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(
        name="Documentation",
        config={
            "URL_ALLOWLIST": r"/docs(?:/|[?#]|$)",
            "URL_DENYLIST": "(?i)/private(?:/|[?#]|$)\nblocked.example.com",
        },
    )
    response = post_site(
        admin_client,
        persona=str(persona.pk),
        include_subdomains="on",
        url_filters_denylist=r"/draft(?:/|[?#]|$)",
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.persona_id == persona.pk
    assert crawl.config["URL_ALLOWLIST"] == persona.config["URL_ALLOWLIST"]
    assert crawl.url_passes_filters("https://example.com/docs")
    assert crawl.url_passes_filters("https://guide.example.com/docs/chapter")
    for url in (
        "https://example.com/unrelated",
        "https://example.com/docs/PRIVATE",
        "https://example.com/docs/draft",
        "https://blocked.example.com/docs",
        "https://deep.blocked.example.com/docs",
    ):
        assert not crawl.url_passes_filters(url), url
    # A selected persona's explicit allowlist keeps native OR semantics.
    assert crawl.url_passes_filters("https://example.org/docs")


def test_site_subpath_keeps_literal_file_path_and_boundaries(admin_client):
    from archivebox.crawls.models import Crawl

    response = post_site(
        admin_client,
        url="https://example.com/docs/file.html?edition=1",
        url_filters_subpaths_only="on",
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    for url in (
        "https://example.com/docs/file.html",
        "http://example.com/docs/file.html/chapter",
        "https://example.com/docs/file.html?edition=2",
        "https://example.com/docs/file.html#section",
    ):
        assert crawl.url_passes_filters(url), url
    for url in (
        "https://example.com/docs/",
        "https://example.com/docs/another.html",
        "https://example.com/docs/file.html2",
        "https://example.com/docs/fileXhtml",
        "https://example.com/docs/FILE.html",
        "https://example.org/docs/file.html",
    ):
        assert not crawl.url_passes_filters(url), url


def test_site_filters_preserve_explicit_native_domain_allowlist(admin_client):
    from archivebox.crawls.models import Crawl

    response = post_site(
        admin_client,
        include_subdomains="on",
        url_filters_same_domain_only="on",
        url_filters_allowlist="example.com\nother.example",
        url_filters_denylist="blocked.example.com",
    )
    assert response.status_code == 302
    crawl = Crawl.objects.get()
    assert crawl.config["URL_ALLOWLIST"] == "example.com\nother.example"
    assert crawl.url_passes_filters("https://example.com/docs")
    assert crawl.url_passes_filters("https://child.example.com/docs")
    assert crawl.url_passes_filters("https://deep.child.example.com/docs")
    assert crawl.url_passes_filters("https://other.example/docs")
    for url in (
        "https://blocked.example.com/docs",
        "https://unlisted.example/docs",
    ):
        assert not crawl.url_passes_filters(url), url


def test_invalid_domain_pattern_propagates_validation_error():
    from archivebox.core.models import Snapshot

    with pytest.raises(ValueError):
        Snapshot.objects.filter_by_patterns(["https://example.com/path"], filter_type="domain")
