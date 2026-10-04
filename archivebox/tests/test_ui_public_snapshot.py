"""Public snapshot UI tests."""

import json
import re

import pytest
import requests
from django.test import override_settings

from archivebox.core.middleware import ADMIN_LOGIN_HINT_COOKIE
from archivebox.tests.conftest import WEB_TEST_HOST
from archivebox.tests.conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_server,
    get_http_response,
    localhost_session,
    wait_for_snapshot_capture,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db


def _login_admin_over_full_server(port: int) -> tuple[requests.Session, str]:
    session = localhost_session()
    get_http_response(port, host=f"admin.archivebox.localhost:{port}", path="/admin/login/")
    login_page = session.get(
        f"http://admin.archivebox.localhost:{port}/admin/login/",
        timeout=10,
    )
    assert login_page.status_code == 200
    csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
    assert csrf_match, login_page.text[:500]
    login_response = session.post(
        f"http://admin.archivebox.localhost:{port}/admin/login/",
        headers={"Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
        data={
            "username": "apitestadmin",
            "password": "testpass123",
            "csrfmiddlewaretoken": csrf_match.group(1),
            "next": "/add/",
        },
        timeout=10,
        allow_redirects=False,
    )
    assert login_response.status_code in (302, 303), login_response.text
    add_page = session.get(
        f"http://admin.archivebox.localhost:{port}/add/",
        headers={"Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
        timeout=10,
    )
    assert add_page.status_code == 200
    add_csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', add_page.text)
    assert add_csrf_match, add_page.text[:500]
    return session, add_csrf_match.group(1)


def _create_private_snapshot_over_full_server(
    data_dir,
    session: requests.Session,
    port: int,
    csrf_token: str,
    url: str,
) -> dict[str, str]:
    response = session.post(
        f"http://admin.archivebox.localhost:{port}/add/",
        headers={"Referer": f"http://admin.archivebox.localhost:{port}/add/"},
        data={
            "url": url,
            "depth": "0",
            "max_urls": "1",
            "crawl_max_size": "0",
            "crawl_timeout": "0",
            "snapshot_max_size": "0",
            "crawl_max_concurrent_snapshots": "1",
            "main_plugins": ["wget"],
            "tag": "private-replay-auth",
            "url_filters_allowlist": r"127\.0\.0\.1[:/].*",
            "url_filters_denylist": "",
            "schedule": "",
            "notes": "private replay auth regression fixture",
            "persona": "Default",
            "permissions": "private",
            "start_paused": "",
            "config": "{}",
            "csrfmiddlewaretoken": csrf_token,
        },
        timeout=10,
        allow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text

    # Let the running server consume its own /add/ submission, as it does for
    # users. Manually driving a stopped runner would hide queue/lifecycle bugs.
    wait_for_snapshot_capture(data_dir, url, timeout=120)

    with use_archivebox_db(data_dir):
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.select_related("crawl").get(url=url)
        snapshot_id = str(snapshot.id)
        return {
            "id": snapshot_id,
            "path": snapshot.url_path,
            "host": f"snap-{snapshot_id.replace('-', '')[-12:]}.archivebox.localhost:{port}",
        }


def _logout_admin_over_full_server(session: requests.Session, port: int) -> None:
    admin_page = session.get(
        f"http://admin.archivebox.localhost:{port}/admin/",
        timeout=10,
    )
    assert admin_page.status_code == 200, admin_page.text
    assert 'class="navbar-logout-form"' in admin_page.text
    assert 'method="post"' in admin_page.text
    assert 'action="/admin/logout/"' in admin_page.text

    csrf_token = next((cookie.value for cookie in session.cookies if cookie.name.startswith("archivebox_csrftoken_")), "")
    assert csrf_token
    response = session.post(
        f"http://admin.archivebox.localhost:{port}/admin/logout/",
        headers={"Referer": f"http://admin.archivebox.localhost:{port}/admin/"},
        data={"csrfmiddlewaretoken": csrf_token},
        timeout=10,
        allow_redirects=False,
    )
    assert response.status_code in (200, 302, 303), response.text


def _replay_cookies(session: requests.Session):
    return [cookie for cookie in session.cookies if cookie.name.startswith("archivebox_replay_")]


def _create_admin_user_with_cli(data_dir) -> None:
    result = run_archivebox_cmd(
        [
            "manage",
            "createsuperuser",
            "--noinput",
            "--username",
            "apitestadmin",
            "--email",
            "apitestadmin@example.com",
        ],
        cwd=data_dir,
        env=cli_env(DJANGO_SUPERUSER_PASSWORD="testpass123"),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _create_public_snapshot_with_cli(data_dir, url: str) -> str:
    result = run_archivebox_cmd(
        ["snapshot", "create", "--status", "sealed", "--tag", "public-mode-matrix", url],
        cwd=data_dir,
        env=cli_env(PERMISSIONS="public"),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
    assert records, result.stdout
    snapshot_id = str(records[-1]["id"])

    updated = run_archivebox_cmd(
        ["snapshot", "update", "--status", "sealed"],
        cwd=data_dir,
        env=cli_env(PERMISSIONS="public"),
        input=result.stdout,
        timeout=60,
    )
    assert updated.returncode == 0, updated.stderr or updated.stdout

    listed = run_archivebox_cmd(
        ["snapshot", "list", "--url__icontains", url, "--csv=id,url,status"],
        cwd=data_dir,
        env=cli_env(),
        timeout=60,
    )
    assert listed.returncode == 0, listed.stderr or listed.stdout
    assert snapshot_id in listed.stdout
    assert url in listed.stdout
    assert "sealed" in listed.stdout
    return snapshot_id


@override_settings(PUBLIC_INDEX=True)
def test_archive_url_with_multiple_snapshots_redirects_to_latest_snapshot(client, admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    url = "https://multiple-public-snapshots.example/page"
    first_crawl = Crawl.objects.create(urls=url, created_by=admin_user, config={"PERMISSIONS": "public"})
    second_crawl = Crawl.objects.create(urls=url, created_by=admin_user, config={"PERMISSIONS": "public"})
    first = Snapshot.objects.create(url=url, title="First copy", crawl=first_crawl, status=Snapshot.StatusChoices.SEALED)
    second = Snapshot.objects.create(url=url, title="", crawl=second_crawl, status=Snapshot.StatusChoices.SEALED)
    for plugin, output_size in (("screenshot", 1536), ("singlefile", 2560)):
        ArchiveResult.objects.create(
            snapshot=first,
            plugin=plugin,
            hook_name=f"on_Snapshot__50_{plugin}.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_size=output_size,
        )
    ArchiveResult.refresh_snapshot_output_sizes({first.id})
    ArchiveResult.objects.create(
        snapshot=second,
        plugin="title",
        hook_name="on_Snapshot__10_title.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="Resolved second copy",
    )

    with CaptureQueriesContext(connection) as captured_queries:
        response = client.get(f"/archive/{url}", HTTP_HOST=WEB_TEST_HOST, follow=True)
    assert len(captured_queries) <= 7

    assert response.redirect_chain[0][0].rstrip("/").endswith(second.get_absolute_url().rstrip("/"))
    assert response.status_code == 200
    assert b"Resolved second copy" in response.content
    assert b'aria-label="All captures; selected ' in response.content
    assert b'class="year-capture-count">2</span>' in response.content
    assert b"snapshot-count-badge" not in response.content
    chooser = re.search(
        rb'<details class="snapshot-variants year-variants">.*?</details>',
        response.content,
        re.DOTALL,
    )
    assert chooser
    assert first.get_absolute_url().encode() in chooser.group()
    assert second.get_absolute_url().encode() in chooser.group()
    assert b"4.0\xc2\xa0KB" in chooser.group()
    assert b'aria-current="page"' in chooser.group()
    assert b"\xf0\x9f\x93\x81 2" not in chooser.group()
    assert b"\xf0\x9f\x93\x81 2" not in response.content


def _login_admin_session_over_http(port: int, host: str) -> requests.Session:
    session = requests.Session()
    login_page = session.get(
        f"http://127.0.0.1:{port}/admin/login/",
        headers={"Host": host},
        timeout=10,
    )
    assert login_page.status_code == 200, login_page.text[:500]
    assert "docker compose exec archivebox archivebox manage createsuperuser" in login_page.text
    csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
    assert csrf_match, login_page.text[:500]
    login_response = session.post(
        f"http://127.0.0.1:{port}/admin/login/",
        headers={"Host": host, "Referer": f"http://{host}/admin/login/"},
        data={
            "username": "apitestadmin",
            "password": "testpass123",
            "csrfmiddlewaretoken": csrf_match.group(1),
            "next": "/admin/core/snapshot/",
        },
        timeout=10,
        allow_redirects=False,
    )
    assert login_response.status_code in (302, 303), login_response.text[:500]
    return session


def _response_cookie_names(response: requests.Response) -> set[str]:
    return {cookie.name for cookie in response.cookies}


def _assert_no_admin_cookies_set(response: requests.Response) -> None:
    cookie_names = _response_cookie_names(response)
    assert not any(name.startswith("archivebox_sessionid_") for name in cookie_names), response.headers.get("Set-Cookie", "")
    assert not any(name.startswith("archivebox_csrftoken_") for name in cookie_names), response.headers.get("Set-Cookie", "")


def _assert_only_hint_cookie_set(response: requests.Response) -> None:
    _assert_no_admin_cookies_set(response)
    assert _response_cookie_names(response) <= {ADMIN_LOGIN_HINT_COOKIE}, response.headers.get("Set-Cookie", "")


class TestPublicIndex:
    """Tests for public index visibility and redirects."""

    @override_settings(BASE_URL="", PUBLIC_INDEX=True)
    def test_unconfigured_homepage_starts_admin_setup(self, client):
        response = client.get("/", HTTP_HOST="archivebox.example.test", follow=False)

        assert response.status_code == 302
        assert response["Location"] == "/admin/login/?next=/"

    @pytest.mark.timeout(120)
    @pytest.mark.django_db(transaction=True)
    def test_base_url_redirect_target_is_reachable_over_full_server(self, tmp_path):
        init_archive(tmp_path)
        port = get_free_port()
        env = cli_env(
            port=port,
            server=True,
            BASE_URL=f"http://archivebox.localhost:{port}",
            PUBLIC_INDEX="True",
        )

        try:
            start_archivebox_server(tmp_path, env=env, port=port)
            session = localhost_session()
            response = session.get(
                f"http://archivebox.localhost:{port}/",
                timeout=10,
                allow_redirects=True,
            )

            assert response.status_code == 200
            assert response.url == f"http://web.archivebox.localhost:{port}/public/"
            assert "ArchiveBox" in response.text
        finally:
            stop_server(tmp_path)

    @override_settings(PUBLIC_INDEX=True)
    def test_public_index_lists_only_public_snapshots(self, client, admin_user):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        public_crawl = Crawl.objects.create(urls="https://public.example", created_by=admin_user, config={"PERMISSIONS": "public"})
        unlisted_crawl = Crawl.objects.create(urls="https://unlisted.example", created_by=admin_user, config={"PERMISSIONS": "unlisted"})
        private_crawl = Crawl.objects.create(urls="https://private.example", created_by=admin_user, config={"PERMISSIONS": "private"})
        Snapshot.objects.create(
            url="https://public.example",
            title="Public Snapshot",
            crawl=public_crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        Snapshot.objects.create(
            url="https://unlisted.example",
            title="Unlisted Snapshot",
            crawl=unlisted_crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        Snapshot.objects.create(
            url="https://private.example",
            title="Private Snapshot",
            crawl=private_crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

        response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)

        assert response.status_code == 200
        assert b"Public Snapshot" in response.content
        assert b"Unlisted Snapshot" not in response.content
        assert b"Private Snapshot" not in response.content

    @override_settings(PUBLIC_INDEX=True)
    def test_public_index_loads_card_metadata_in_one_result_query(self, client, admin_user):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(urls="https://public-results.example", created_by=admin_user, config={"PERMISSIONS": "public"})
        snapshot = Snapshot.objects.create(
            url="https://public-results.example",
            title="Public result loading",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        migrated_singlefile = snapshot.output_dir / "singlefile.html"
        migrated_singlefile.parent.mkdir(parents=True, exist_ok=True)
        migrated_singlefile.write_text("<html>migrated output</html>", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="readability",
            hook_name="on_Snapshot__50_readability.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"content.html": {"size": 100_000}},
            output_str="unused" * 10_000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"singlefile.html": {"size": migrated_singlefile.stat().st_size, "root_relative": True}},
            output_str="singlefile.html",
            output_size=migrated_singlefile.stat().st_size,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            hook_name="on_Snapshot__50_screenshot.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"screenshot.png": {"size": 2048}},
        )

        with CaptureQueriesContext(connection) as captured_queries:
            response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)

        result_queries = [query["sql"].lower() for query in captured_queries if "core_archiveresult" in query["sql"].lower()]
        row_lookups = [
            query["sql"]
            for query in captured_queries
            if re.search(r'WHERE "(?:core_snapshot|crawls_crawl|auth_user)"\."id" =', query["sql"])
        ]
        assert row_lookups == [], "Public rows must reuse the page's snapshot, crawl, and owner metadata"
        assert len(result_queries) == 1
        assert "output_files" in result_queries[0]
        assert "output_str" in result_queries[0]
        assert response.status_code == 200
        screenshot_result = ArchiveResult.objects.get(snapshot=snapshot, plugin="screenshot")
        assert f"_card/{screenshot_result.id}".encode() in response.content
        expected_path = f"/{snapshot.archive_path_from_db}#singlefile".encode()
        assert expected_path in response.content
        assert f"/{snapshot.archive_path_from_db}/singlefile/".encode() not in response.content
        assert b"files-icon-pile--html" in response.content
        assert b"files-icon-pile--raster" in response.content
        assert b'data-tooltip="singlefile"' in response.content
        assert b'title="singlefile"' not in response.content

    @override_settings(PUBLIC_INDEX=True)
    @pytest.mark.django_db(transaction=True)
    def test_public_count_uses_permission_index_for_uniform_visibility(self, client, admin_user):
        import time

        from django.core.cache import cache
        from django.db import connection
        from django.db.backends.signals import connection_created
        from django.test.utils import CaptureQueriesContext
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(urls="https://public-count.example", created_by=admin_user, config={"PERMISSIONS": "public"})
        Snapshot.objects.bulk_create(
            [
                Snapshot(
                    url=f"https://public-count.example/{index}",
                    timestamp=str(1800000000 + index),
                    crawl=crawl,
                    config={"PERMISSIONS": "public"},
                    status="sealed",
                )
                for index in range(125)
            ],
        )
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("ANALYZE core_snapshot")

        key = "progress-collection:public"
        cache.delete_many([key, f"{key}:refresh"])
        background_queries = []

        def observe(execute, sql, params, many, context):
            background_queries.append((sql, params))
            return execute(sql, params, many, context)

        def observe_background_connection(sender, connection, **kwargs):
            connection.execute_wrappers.append(observe)

        connection_created.connect(observe_background_connection)
        try:
            with CaptureQueriesContext(connection) as queries:
                response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)

            assert response.status_code == 200
            assert not any("COUNT(" in q["sql"] for q in queries), "Public page loads must not wait for a count"
            assert response.context["public_snapshot_count"] is None
            assert len(response.context["object_list"]) == 50
            assert response.context["page_obj"].has_next()
            assert b"of 125" not in response.content

            deadline = time.monotonic() + 5
            while cache.get(key) is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert cache.get(key)["snapshots"] == 125

            reloaded = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
            assert reloaded.context["public_snapshot_count"] == 125
            assert b"of 125" in reloaded.content
            last_page = client.get("/public/?page=3", HTTP_HOST=WEB_TEST_HOST)
            assert len(last_page.context["object_list"]) == 25
            assert not last_page.context["page_obj"].has_next()
            assert client.get("/public/?page=4", HTTP_HOST=WEB_TEST_HOST).status_code == 404

            # The runner can add a page before the cached total refreshes.
            # Navigation follows actual rows, never the old cached page count.
            Snapshot.objects.bulk_create(
                [
                    Snapshot(
                        url=f"https://public-count.example/{index}",
                        timestamp=str(1800000000 + index),
                        crawl=crawl,
                        config={"PERMISSIONS": "public"},
                        status="sealed",
                    )
                    for index in range(125, 160)
                ],
            )
            added_page = client.get("/public/?page=4", HTTP_HOST=WEB_TEST_HOST)
            assert added_page.status_code == 200
            assert len(added_page.context["object_list"]) == 10
            assert not added_page.context["page_obj"].has_next()
            assert added_page.context["public_snapshot_count"] == 160
            assert cache.get(key)["snapshots"] == 125

            count_queries = [(sql, params) for sql, params in background_queries if "COUNT(" in sql and '"core_snapshot"' in sql]
            assert len(count_queries) == 1, "Reloads must reuse the cached total"
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("EXPLAIN QUERY PLAN " + count_queries[0][0], count_queries[0][1])
                    plan = " ".join(str(row[-1]) for row in cursor.fetchall())
                assert "SEARCH core_snapshot USING INDEX" in plan and "permissions>" in plan, plan
        finally:
            connection_created.disconnect(observe_background_connection)

    @override_settings(PUBLIC_INDEX=True)
    def test_upgraded_07_snapshot_icon_target_renders_at_extensionless_live_url(self, client, admin_user):
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.routes_util import get_snapshot_host
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(urls="https://upgraded-07.example", created_by=admin_user, config={"PERMISSIONS": "public"})
        snapshot = Snapshot.objects.create(
            url="https://upgraded-07.example",
            title="Upgraded 0.7 snapshot",
            crawl=crawl,
            fs_version="0.7.0",
            status=Snapshot.StatusChoices.SEALED,
        )
        migrated_output = snapshot.output_dir / "singlefile.html"
        migrated_output.parent.mkdir(parents=True, exist_ok=True)
        migrated_output.write_text("<html>migrated output</html>", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="singlefile.html",
            # 0.9.50 could import the old root file without recording the later
            # root_relative marker, leaving the DB and filesystem half-migrated.
            output_files={"singlefile.html": {"size": migrated_output.stat().st_size}},
            output_size=migrated_output.stat().st_size,
        )

        public_index = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
        expected_target = f"/{snapshot.archive_path_from_db}#singlefile"
        assert expected_target.encode() in public_index.content

        live_detail = client.get(f"/{snapshot.archive_path_from_db}", HTTP_HOST=WEB_TEST_HOST, follow=False)
        legacy_index = client.get(f"/{snapshot.archive_path_from_db}/index.html", HTTP_HOST=WEB_TEST_HOST, follow=False)
        saved_file = client.get("/singlefile/singlefile.html", HTTP_HOST=get_snapshot_host(str(snapshot.id)), follow=False)
        historic_icon_target = client.get(
            f"/{snapshot.archive_path_from_db}/singlefile/singlefile.html",
            HTTP_HOST=WEB_TEST_HOST,
            follow=True,
        )
        assert live_detail.status_code == 200
        assert legacy_index.status_code == 200
        assert saved_file.status_code == 200
        assert historic_icon_target.status_code == 200
        assert historic_icon_target.redirect_chain
        assert b"migrated output" in b"".join(saved_file.streaming_content)
        assert b"migrated output" in b"".join(historic_icon_target.streaming_content)
        assert b"Upgraded 0.7 snapshot" in live_detail.content

    @override_settings(PUBLIC_INDEX=True)
    def test_public_index_renders_title_html_entities_once(self, client, admin_user):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://title-entities.example",
            created_by=admin_user,
            config={"PERMISSIONS": "public"},
        )
        snapshot = Snapshot.objects.create(
            url="https://title-entities.example",
            title="Nick Sweeting: Blog &amp; Projects - HedgeDoc",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

        snapshot.refresh_from_db()
        assert snapshot.title == "Nick Sweeting: Blog & Projects - HedgeDoc"

        # Rows created before title normalization was fixed must render correctly
        # without requiring a database rewrite.
        Snapshot.objects.filter(pk=snapshot.pk).update(title="Nick Sweeting: Blog &amp; Projects - HedgeDoc")
        response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)

        assert response.status_code == 200
        assert b"Nick Sweeting: Blog &amp; Projects - HedgeDoc" in response.content
        assert b"Nick Sweeting: Blog &amp;amp; Projects - HedgeDoc" not in response.content

    @override_settings(PUBLIC_INDEX=True)
    def test_public_snapshot_surfaces_escape_legacy_raw_title_and_tag_values(self, client, admin_user):
        from archivebox.core.models import ArchiveResult, Snapshot, Tag
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(urls="https://public-xss.example", created_by=admin_user, config={"PERMISSIONS": "public"})
        snapshot = Snapshot.objects.create(
            url="https://public-xss.example",
            title="Safe title before raw SQL",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        tag = Tag.objects.create(name="safe-tag-before-raw-sql")
        snapshot.tags.add(tag)
        snapshot_archive_path = snapshot.archive_path

        title_payload = "Legacy title 1 < 2 & 3 </script><script id=public-title-xss>window.__archivebox_public_title_xss__=1</script>"
        tag_payload = "</script><script id=public-tag-xss>window.__archivebox_public_tag_xss__=1</script>"
        url_payload = "https://public-xss.example/</script><script id=public-url-xss>window.__archivebox_public_url_xss__=1</script>"
        filename_payload = 'evil"><script id=public-file-xss>window.__archivebox_public_file_xss__=1</script>.txt'
        Snapshot.objects.filter(pk=snapshot.pk).update(title=title_payload, url=url_payload)
        Tag.objects.filter(pk=tag.pk).update(name=tag_payload)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="staticfile",
            hook_name="on_Snapshot__00_staticfile.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={filename_payload: {"size": 12, "mimetype": "text/plain"}},
        )

        public_index = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
        snapshot_detail = client.get(f"/{snapshot_archive_path}/index.html", HTTP_HOST=WEB_TEST_HOST)

        assert public_index.status_code == 200
        assert snapshot_detail.status_code == 200
        for response in (public_index, snapshot_detail):
            assert b"<script id=public-title-xss>" not in response.content
            assert b"<script id=public-tag-xss>" not in response.content
            assert b"<script id=public-url-xss>" not in response.content
            assert b"<script id=public-file-xss>" not in response.content
            assert b"&lt;/script&gt;&lt;script id=public-tag-xss&gt;" in response.content
        assert b"&lt;/script&gt;&lt;script id=public-title-xss&gt;" in public_index.content
        assert b"window.__archivebox_public_title_xss__=1" in snapshot_detail.content
        assert b"Legacy title 1 &lt; 2 &amp; 3" in snapshot_detail.content
        assert b"Legacy title 1 &amp;lt; 2 &amp;amp; 3" not in snapshot_detail.content
        assert b"&lt;script id=public-file-xss&gt;" in snapshot_detail.content

    def test_direct_snapshot_urls_allow_unlisted_but_not_private_for_guests(self, client, admin_user):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        unlisted_crawl = Crawl.objects.create(urls="https://unlisted.example", created_by=admin_user, config={"PERMISSIONS": "unlisted"})
        private_crawl = Crawl.objects.create(urls="https://private.example", created_by=admin_user, config={"PERMISSIONS": "private"})
        unlisted_snapshot = Snapshot.objects.create(
            url="https://unlisted.example",
            crawl=unlisted_crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        private_snapshot = Snapshot.objects.create(url="https://private.example", crawl=private_crawl, status=Snapshot.StatusChoices.SEALED)

        unlisted_response = client.get(f"/snapshot/{unlisted_snapshot.id}/", HTTP_HOST=WEB_TEST_HOST)
        private_response = client.get(f"/snapshot/{private_snapshot.id}/", HTTP_HOST=WEB_TEST_HOST)

        assert unlisted_response.status_code == 302
        assert unlisted_response["Location"].rstrip("/").endswith(unlisted_snapshot.get_absolute_url().rstrip("/"))
        assert client.get(f"{unlisted_snapshot.get_absolute_url()}/index.html", HTTP_HOST=WEB_TEST_HOST).status_code == 200
        assert private_response.status_code == 302
        assert "/admin/core/snapshot/replay-auth/" in private_response["Location"]

    def test_requested_url_snapshot_path_does_not_expose_private_snapshot(self, client, admin_user):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        private_url = "https://private-url-path.example/secret"
        private_crawl = Crawl.objects.create(urls=private_url, created_by=admin_user, config={"PERMISSIONS": "private"})
        private_snapshot = Snapshot.objects.create(url=private_url, crawl=private_crawl, status=Snapshot.StatusChoices.SEALED)
        date = private_snapshot.bookmarked_at.strftime("%Y%m%d")

        response = client.get(
            f"/{admin_user.username}/{date}/{private_url}",
            HTTP_HOST=WEB_TEST_HOST,
        )

        assert response.status_code == 404
        assert str(private_snapshot.id) not in response.content.decode()

    @pytest.mark.timeout(180)
    @pytest.mark.django_db(transaction=True)
    def test_private_snapshot_bookmark_authorizes_logged_in_admin_with_snap_scoped_replay_cookie(
        self,
        tmp_path,
        recursive_test_site,
    ):
        init_archive(tmp_path)
        create_admin_and_token(tmp_path)
        port = get_free_port()
        env = cli_env(
            port=port,
            server=True,
            SERVER_SECURITY_MODE="safe-subdomains-fullreplay",
            PUBLIC_ADD_VIEW="True",
            PUBLIC_INDEX="True",
        )

        try:
            start_archivebox_server(tmp_path, env=env, port=port)
            session, csrf_token = _login_admin_over_full_server(port)
            snapshot = _create_private_snapshot_over_full_server(
                tmp_path,
                session,
                port,
                csrf_token,
                recursive_test_site["root_url"],
            )
            snap_url = f"http://{snapshot['host']}/index.html"

            response = session.get(snap_url, timeout=10, allow_redirects=True)

            assert response.status_code == 200
            assert response.url == snap_url
            assert recursive_test_site["root_url"] in response.text
            assert "/admin/login/" not in response.url
            assert "/admin/login/" not in response.text

            replay_cookies = _replay_cookies(session)
            assert replay_cookies
            assert any(cookie.domain == snapshot["host"].split(":", 1)[0] for cookie in replay_cookies)
            assert not any(cookie.domain in {"archivebox.localhost", ".archivebox.localhost"} for cookie in replay_cookies)
        finally:
            stop_server(tmp_path)

    @pytest.mark.timeout(180)
    @pytest.mark.django_db(transaction=True)
    def test_private_snapshot_replay_cookie_stops_working_after_admin_logout(
        self,
        tmp_path,
        recursive_test_site,
    ):
        init_archive(tmp_path)
        create_admin_and_token(tmp_path)
        port = get_free_port()
        env = cli_env(
            port=port,
            server=True,
            SERVER_SECURITY_MODE="safe-subdomains-fullreplay",
            PUBLIC_ADD_VIEW="True",
            PUBLIC_INDEX="True",
        )

        try:
            start_archivebox_server(tmp_path, env=env, port=port)
            session, csrf_token = _login_admin_over_full_server(port)
            snapshot = _create_private_snapshot_over_full_server(
                tmp_path,
                session,
                port,
                csrf_token,
                recursive_test_site["root_url"],
            )
            snap_url = f"http://{snapshot['host']}/index.html"

            authorized = session.get(snap_url, timeout=10, allow_redirects=True)
            assert authorized.status_code == 200
            assert authorized.url == snap_url
            assert _replay_cookies(session)

            _logout_admin_over_full_server(session, port)

            stale_replay = session.get(snap_url, timeout=10, allow_redirects=False)
            assert stale_replay.status_code in (302, 303)
            assert "/admin/core/snapshot/replay-auth/" in stale_replay.headers["Location"]

            logged_out = session.get(snap_url, timeout=10, allow_redirects=True)
            assert "/admin/login/" in logged_out.url
            assert logged_out.url != snap_url
        finally:
            stop_server(tmp_path)

    @override_settings(PUBLIC_INDEX=True)
    def test_public_index_redirects_logged_in_users_to_admin_snapshot_list(self, client, admin_user):
        client.force_login(admin_user)
        client.cookies[ADMIN_LOGIN_HINT_COOKIE] = "1"

        response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)

        assert response.status_code == 302
        assert response["Location"] == "/admin/core/snapshot/"


@pytest.mark.timeout(240)
@pytest.mark.parametrize(
    "mode",
    [
        "safe-subdomains-fullreplay",
        "safe-onedomain-nojsreplay",
        "unsafe-onedomain-noadmin",
        "danger-onedomain-fullreplay",
    ],
)
def test_public_web_routing_and_auth_cookie_behavior_over_real_server_in_all_security_modes(tmp_path, mode):
    init_archive(tmp_path)
    _create_admin_user_with_cli(tmp_path)
    public_url = f"https://public-mode-{mode}.example"
    _create_public_snapshot_with_cli(tmp_path, public_url)

    port = get_free_port()
    base_host = f"archivebox.localhost:{port}"
    admin_host = f"admin.archivebox.localhost:{port}" if mode == "safe-subdomains-fullreplay" else base_host
    web_host = f"web.archivebox.localhost:{port}" if mode == "safe-subdomains-fullreplay" else base_host
    api_host = f"api.archivebox.localhost:{port}" if mode == "safe-subdomains-fullreplay" else base_host
    env = cli_env(
        port=port,
        server=True,
        BASE_URL=f"http://archivebox.localhost:{port}",
        SERVER_SECURITY_MODE=mode,
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="False",
        PERMISSIONS="public",
    )

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        get_http_response(port, host=web_host, path="/public/")

        public_page = requests.get(
            f"http://127.0.0.1:{port}/public/",
            headers={"Host": web_host},
            timeout=10,
            allow_redirects=False,
        )
        assert public_page.status_code == 200, public_page.text[:500]
        assert public_url in public_page.text
        if mode == "safe-subdomains-fullreplay":
            _assert_only_hint_cookie_set(public_page)

        add_page = requests.get(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": web_host},
            timeout=10,
            allow_redirects=False,
        )
        if mode == "unsafe-onedomain-noadmin":
            assert add_page.status_code == 403
        else:
            assert add_page.status_code in (301, 302), add_page.text[:500]
            assert "/admin/login/" in add_page.headers["Location"] or "/add/" in add_page.headers["Location"]
            if mode == "safe-subdomains-fullreplay":
                _assert_only_hint_cookie_set(add_page)

        admin_login = requests.get(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": admin_host},
            timeout=10,
            allow_redirects=False,
        )
        if mode == "unsafe-onedomain-noadmin":
            assert admin_login.status_code == 403
            unsafe_post = requests.post(
                f"http://127.0.0.1:{port}/public/",
                headers={"Host": web_host},
                data={"x": "1"},
                timeout=10,
                allow_redirects=False,
            )
            assert unsafe_post.status_code == 403
            api_docs = requests.get(
                f"http://127.0.0.1:{port}/api/v1/docs",
                headers={"Host": api_host},
                timeout=10,
                allow_redirects=False,
            )
            assert api_docs.status_code == 403
        else:
            assert admin_login.status_code == 200, admin_login.text[:500]
            session = _login_admin_session_over_http(port, admin_host)
            assert any(cookie.name.startswith("archivebox_sessionid_") for cookie in session.cookies)
            for cookie in list(session.cookies):
                if cookie.name == ADMIN_LOGIN_HINT_COOKIE:
                    session.cookies.clear(domain=cookie.domain, path=cookie.path, name=cookie.name)

            logged_in_public_page = session.get(
                f"http://127.0.0.1:{port}/public/",
                headers={"Host": web_host},
                timeout=10,
                allow_redirects=False,
            )
            if mode == "safe-subdomains-fullreplay":
                assert logged_in_public_page.status_code == 200, logged_in_public_page.headers.get("Location")
                assert public_url in logged_in_public_page.text
                _assert_only_hint_cookie_set(logged_in_public_page)

                session.cookies.set(ADMIN_LOGIN_HINT_COOKIE, "1", path="/")
                hinted_public_page = session.get(
                    f"http://127.0.0.1:{port}/public/",
                    headers={"Host": web_host},
                    timeout=10,
                    allow_redirects=False,
                )
                assert hinted_public_page.status_code in (301, 302)
                assert hinted_public_page.headers["Location"] == f"http://{admin_host}/admin/core/snapshot/"
                _assert_only_hint_cookie_set(hinted_public_page)
            else:
                assert logged_in_public_page.status_code in (301, 302)
                assert logged_in_public_page.headers["Location"] == "/admin/core/snapshot/"
    finally:
        stop_server(tmp_path)
