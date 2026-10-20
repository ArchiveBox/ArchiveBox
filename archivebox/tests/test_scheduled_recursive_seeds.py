"""Recurring discovery must refresh its seed without recapturing old children."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("depth", [0, 1])
def test_scheduled_only_new_refreshes_recursive_seed_only(initialized_archive, tmp_path, depth):
    site = tmp_path / "site"
    site.mkdir()
    root = site / "index.html"
    root.write_text('<!doctype html><h1>First edition</h1><a href="/old.html">Old article</a>')
    (site / "old.html").write_text("<!doctype html><h1>Old article</h1>")
    (site / "new.html").write_text("<!doctype html><h1>New article</h1>")
    env = cli_env(
        PLUGINS="wget,parse_html_urls",
        ONLY_NEW="true",
        TIMEOUT="20",
        CRAWL_MAX_CONCURRENT_SNAPSHOTS="1",
    )
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(site))) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/"

        def command(*args):
            return run_archivebox_cmd(list(args), cwd=initialized_archive, env=env, check=True, timeout=90)

        def counts():
            with use_archivebox_db(initialized_archive):
                return {
                    candidate: Snapshot.objects.filter(url=candidate).count() for candidate in (url, url + "old.html", url + "new.html")
                }

        try:
            command("schedule", "--every=daily", f"--depth={depth}", "--only-new", url)
            command("schedule", "--run-all")
            command("run", "--no-stdin")
            assert counts() == {url: 1, url + "old.html": depth, url + "new.html": 0}

            root.write_text(
                '<!doctype html><h1>Second edition</h1><a href="/old.html">Old article</a><a href="/new.html">New article</a>',
            )
            command("schedule", "--run-all")
            command("run", "--no-stdin")
            assert counts() == {url: 1 + depth, url + "old.html": depth, url + "new.html": depth}
            with use_archivebox_db(initialized_archive):
                assert not Crawl.objects.filter(schedule__isnull=False).exclude(status=Crawl.StatusChoices.SEALED).exists()
                if depth:
                    newest = Snapshot.objects.filter(url=url).order_by("-created_at").first()
                    assert newest is not None
                    saved_root = newest.output_dir
                    child = Snapshot.objects.get(url=url + "new.html")
                    assert child.parent_snapshot_id == newest.id
                    assert child.depth == 1
            if depth:
                assert any("Second edition" in path.read_text() for path in saved_root.glob("wget/**/*.html"))

            # An ordinary add retains global ONLY_NEW even when recursive.
            command("add", f"--depth={depth}", "--only-new", "--plugins=wget,parse_html_urls", url)
            assert counts() == {url: 1 + depth, url + "old.html": depth, url + "new.html": depth}
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.django_db(transaction=True)
def test_add_view_schedule_preserves_template_policy_and_explicit_overrides(client, api_admin_user):
    from django.urls import reverse

    from archivebox.crawls.models import CrawlSchedule
    from archivebox.personas.models import Persona
    from archivebox.tests.test_ui_add_view import ADD_FORM_DEFAULTS, ADMIN_HOST

    Persona.get_or_create_default()
    client.force_login(api_admin_user)
    response = client.post(
        reverse("add"),
        data={
            **ADD_FORM_DEFAULTS,
            "url": "https://example.com/scheduled-source",
            "depth": "1",
            "max_urls": "60",
            "url_filters_denylist": r"/blocked(?:/|$)",
            "url_filters_only_new": "1",
            "main_plugins": ["wget"],
            "schedule": "daily",
            "start_paused": "on",
        },
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 302, response.content.decode()
    schedule = CrawlSchedule.objects.select_related("template").get()
    template = schedule.template
    assert template.config["URL_DENYLIST"] == r"/blocked(?:/|$)"
    assert template.config["PLUGINS"] == "wget"
    assert template.config["CRAWL_MAX_URLS"] == 60
    original_template_config = dict(template.config)
    first = schedule.enqueue()
    assert first.config == {**template.config, **schedule.config}
    assert first.url_passes_filters("https://example.com/blocked/page", use_effective_config=False) is False

    # Explicit empty/false/zero schedule overrides must not inherit template values.
    schedule.config = {"URL_DENYLIST": "", "ONLY_NEW": False, "CRAWL_MAX_URLS": 0, "SCHEDULE_KIND": "crawl"}
    schedule.save(update_fields=["config"])
    second = schedule.enqueue()
    assert second.config["PLUGINS"] == "wget"
    assert second.config["URL_DENYLIST"] == ""
    assert second.config["ONLY_NEW"] is False
    assert second.config["CRAWL_MAX_URLS"] == 0
    assert "SCHEDULE_KIND" not in second.config
    template.refresh_from_db()
    assert template.config == original_template_config
