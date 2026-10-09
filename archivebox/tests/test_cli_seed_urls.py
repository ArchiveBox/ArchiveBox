"""Explicit import seeds retain URL bytes and obey user-selected filters."""

import json

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)

JS_PAGE_URLS = (
    "https://github.com/jacomyal/sigma.js",
    "http://harmful.cat-v.org/software/node.js",
    "https://web.archive.org/web/20160507105653/http://summerofgoto.com/js/goto.js",
)


PRESERVED_URLS = (
    "http://accidentalscientist.com/2014/12/why-movies-look-weird-at-48fps-and-games-are-better-at-60fps-and-the-uncanny-valley.html?",
    "http://ds9a.nl/amazing-dna/?",
    'http://extensionizr.com/!#{"modules":["browser-mode","with-js-bg","with-custom-options","no-override","jquerymin"],"boolean_perms":["contentSettings","contextMenus","cookies","notifications","tabs"],"match_ptrns":["*"]}',
    "https://en.wikipedia.org/wiki/0.999...",
    "https://en.wikipedia.org/wiki/NMDA_receptor#:~:text=The%20NMDA%20receptor%20is%20one,(or%20D%2Dserine).",
    "https://meta.wikimedia.org/wiki/So_you%27ve_made_a_mistake_and_it%27s_public...",
    "https://thejh.net/written-stuff/want-to-use-my-wifi?",
    "https://una.im/css-grid/#?",
    "https://www.globalsign.com/ssl/ssl-open-source/?",
    "https://www.nycmesh.net/?",
    "https://www.theatlantic.com/technology/archive/2016/01/amazon-web-services-data-center/423147/?utm_source=atlfb&amp;single_page=true",
)


@pytest.mark.parametrize(
    ("urls", "options", "expected"),
    [
        pytest.param(
            PRESERVED_URLS,
            [],
            set(PRESERVED_URLS),
            id="literal-trailing-punctuation",
        ),
        pytest.param(JS_PAGE_URLS, [], set(JS_PAGE_URLS), id="explicit-js-page-seeds"),
        pytest.param(
            JS_PAGE_URLS,
            ["--url-denylist=github.com"],
            set(JS_PAGE_URLS[1:]),
            id="explicit-denylist-still-applies",
        ),
    ],
)
def test_add_preserves_explicit_seed_urls(initialized_archive, urls, options, expected):
    source = "\n".join(urls)
    result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=hashes", *options],
        input=source,
        cwd=initialized_archive,
        env=cli_env(),
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        assert crawl.urls.strip() == source
        snapshots = list(Snapshot.objects.filter(crawl=crawl))
        assert {snapshot.url for snapshot in snapshots} == expected
        assert crawl.count_urls_for_limit() == len(urls)
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert all(snapshot.depth == 0 and snapshot.status == Snapshot.StatusChoices.SEALED for snapshot in snapshots)
        assert ArchiveResult.objects.filter(snapshot__crawl=crawl, plugin="hashes").count() == len(expected)


@pytest.mark.parametrize("jsonl", [False, True])
def test_crawl_materializes_structured_urls_without_prose_cleanup(admin_user, jsonl):
    urls = PRESERVED_URLS
    source = "\n".join(json.dumps({"url": url, "depth": 0}) if jsonl else url for url in urls)
    crawl = Crawl.objects.create(urls=source, created_by=admin_user)
    created = crawl.create_snapshots_from_urls()
    assert {snapshot.url for snapshot in created} == set(urls)
    assert crawl.count_urls_for_limit() == len(urls)


def test_crawl_appends_literal_url_records_without_changing_queue_capacity(admin_user):
    crawl = Crawl.objects.create(urls=PRESERVED_URLS[0], created_by=admin_user)
    for url in PRESERVED_URLS[1:]:
        assert crawl.add_url({"url": url, "depth": 0})
    assert crawl.get_urls_list() == list(PRESERVED_URLS)
    assert crawl.count_urls_for_limit() == len(PRESERVED_URLS)
    assert {snapshot.url for snapshot in crawl.create_snapshots_from_urls()} == set(PRESERVED_URLS)
    assert crawl.count_urls_for_limit() == len(PRESERVED_URLS)
