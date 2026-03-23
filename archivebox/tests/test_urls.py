import os
import sys
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _merge_pythonpath(env: dict[str, str]) -> dict[str, str]:
    env.pop("DATA_DIR", None)
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{pythonpath}"
    else:
        env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _run_python(script: str, cwd: Path, timeout: int = 60, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = _merge_pythonpath(os.environ.copy())
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-"],
        cwd=cwd,
        env=env,
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _build_script(body: str) -> str:
    prelude = textwrap.dedent(
        """
    import os
    from pathlib import Path

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
    import django
    django.setup()

    from django.test import Client
    from django.contrib.auth import get_user_model

    from archivebox.core.models import Snapshot, ArchiveResult
    from archivebox.config.common import SERVER_CONFIG
    from archivebox.core.host_utils import (
        get_admin_host,
        get_admin_base_url,
        get_api_host,
        get_web_host,
        get_web_base_url,
        get_public_host,
        get_snapshot_subdomain,
        get_snapshot_host,
        get_original_host,
        get_listen_subdomain,
        split_host_port,
        host_matches,
        is_snapshot_subdomain,
        build_admin_url,
        build_snapshot_url,
    )

    def response_body(resp):
        if getattr(resp, "streaming", False):
            return b"".join(resp.streaming_content)
        return resp.content

    def ensure_admin_user():
        User = get_user_model()
        admin, _ = User.objects.get_or_create(
            username="testadmin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
        )
        admin.set_password("testpassword")
        admin.save()
        return admin

    def get_snapshot():
        snapshot = Snapshot.objects.order_by("-created_at").first()
        assert snapshot is not None, "Expected real_archive_with_example to seed a snapshot"
        return snapshot

    def get_snapshot_files(snapshot):
        output_rel = None
        reserved_snapshot_paths = {"index.html"}
        for output in snapshot.discover_outputs():
            candidate = output.get("path")
            if not candidate:
                continue
            if candidate.startswith("responses/"):
                continue
            if Path(snapshot.output_dir, candidate).is_file():
                output_rel = candidate
                break
        if output_rel is None:
            fallback = Path(snapshot.output_dir, "index.jsonl")
            if fallback.exists():
                output_rel = "index.jsonl"
        assert output_rel is not None

        responses_root = Path(snapshot.output_dir) / "responses" / snapshot.domain
        assert responses_root.exists()
        response_file = None
        response_rel = None
        for candidate in responses_root.rglob("*"):
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(responses_root)
            if str(rel) in reserved_snapshot_paths:
                continue
            if not (Path(snapshot.output_dir) / rel).exists():
                response_file = candidate
                response_rel = str(rel)
                break
        if response_file is None:
            for candidate in responses_root.rglob("*"):
                if not candidate.is_file():
                    continue
                rel = candidate.relative_to(responses_root)
                if str(rel) in reserved_snapshot_paths:
                    continue
                response_file = candidate
                response_rel = str(rel)
                break
        if response_file is None:
            response_file = next(p for p in responses_root.rglob("*") if p.is_file())
            response_rel = str(response_file.relative_to(responses_root))
        response_output_path = Path(snapshot.output_dir) / response_rel
        return output_rel, response_file, response_rel, response_output_path

    def write_replay_fixtures(snapshot):
        dangerous_html = Path(snapshot.output_dir) / "dangerous.html"
        dangerous_html.write_text(
            "<!doctype html><html><body><script>window.__archivebox_danger__ = true;</script><h1>Danger</h1></body></html>",
            encoding="utf-8",
        )
        safe_json = Path(snapshot.output_dir) / "safe.json"
        safe_json.write_text('{"ok": true}', encoding="utf-8")
        responses_root = Path(snapshot.output_dir) / "responses" / snapshot.domain
        responses_root.mkdir(parents=True, exist_ok=True)
        sniffed_response = responses_root / "dangerous-response"
        sniffed_response.write_text(
            "<!doctype html><html><body><script>window.__archivebox_response__ = true;</script><p>Response Danger</p></body></html>",
            encoding="utf-8",
        )
        return "dangerous.html", "safe.json", "dangerous-response"
    """,
    )
    return prelude + "\n" + textwrap.dedent(body)


class TestUrlRouting:
    data_dir: Path

    @pytest.fixture(autouse=True)
    def _setup_data_dir(self, real_archive_with_example: Path) -> None:
        self.data_dir = real_archive_with_example

    def _run(
        self,
        body: str,
        timeout: int = 120,
        mode: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        script = _build_script(body)
        merged_env = dict(env_overrides or {})
        if mode:
            merged_env["SERVER_SECURITY_MODE"] = mode
        result = _run_python(
            script,
            cwd=self.data_dir,
            timeout=timeout,
            env_overrides=merged_env or None,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_host_utils_and_public_redirect(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            snapshot_id = str(snapshot.id)
            domain = snapshot.domain

            web_host = get_web_host()
            admin_host = get_admin_host()
            api_host = get_api_host()
            public_host = get_public_host()
            snapshot_subdomain = get_snapshot_subdomain(snapshot_id)
            snapshot_host = get_snapshot_host(snapshot_id)
            original_host = get_original_host(domain)
            base_host = SERVER_CONFIG.LISTEN_HOST

            host_only, port = split_host_port(base_host)
            assert host_only == "archivebox.localhost"
            assert port == "8000"
            assert web_host == "web.archivebox.localhost:8000"
            assert admin_host == "admin.archivebox.localhost:8000"
            assert api_host == "api.archivebox.localhost:8000"
            assert public_host == "public.archivebox.localhost:8000"
            assert snapshot_subdomain == f"snap-{snapshot_id[-12:].lower()}"
            assert snapshot_host == f"{snapshot_subdomain}.archivebox.localhost:8000"
            assert original_host == f"{domain}.archivebox.localhost:8000"
            assert get_listen_subdomain(web_host) == "web"
            assert get_listen_subdomain(admin_host) == "admin"
            assert get_listen_subdomain(api_host) == "api"
            assert get_listen_subdomain(snapshot_host) == snapshot_subdomain
            assert get_listen_subdomain(original_host) == domain
            assert get_listen_subdomain(base_host) == ""
            assert host_matches(web_host, get_web_host())
            assert is_snapshot_subdomain(snapshot_subdomain)
            assert is_snapshot_subdomain(snapshot_id)

            client = Client()
            resp = client.get("/public.html", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"].endswith("/public/")

            resp = client.get("/public/", HTTP_HOST=base_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"].startswith(f"http://{web_host}/public/")

            resp = client.get("/", HTTP_HOST=api_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"].startswith("/api/")

            print("OK")
            """,
        )

    def test_web_admin_routing(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            client = Client()
            web_host = get_web_host()
            public_host = get_public_host()
            admin_host = get_admin_host()
            snapshot_host = get_snapshot_host(str(snapshot.id))
            original_host = get_original_host(snapshot.domain)

            resp = client.get("/admin/login/", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert admin_host in resp["Location"]

            resp = client.get("/admin/login/?next=/admin/", HTTP_HOST=public_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{admin_host}/admin/login/?next=/admin/"

            resp = client.get("/admin/login/?next=/admin/", HTTP_HOST=snapshot_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{admin_host}/admin/login/?next=/admin/"

            resp = client.get("/admin/login/?next=/admin/", HTTP_HOST=original_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{admin_host}/admin/login/?next=/admin/"

            resp = client.get("/admin/login/", HTTP_HOST=admin_host)
            assert resp.status_code == 200

            resp = client.get(f"/{snapshot.url_path}", HTTP_HOST=admin_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{snapshot_host}"

            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=admin_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{snapshot_host}"

            resp = client.get("/static/jquery.min.js", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert "javascript" in (resp.headers.get("Content-Type") or "")

            resp = client.get("/static/jquery.min.js", HTTP_HOST=original_host)
            assert resp.status_code == 200
            assert "javascript" in (resp.headers.get("Content-Type") or "")

            print("OK")
            """,
        )

    def test_snapshot_routing_and_hosts(self) -> None:
        self._run(
            """
            import io
            import zipfile

            snapshot = get_snapshot()
            output_rel, response_file, response_rel, response_output_path = get_snapshot_files(snapshot)
            snapshot_id = str(snapshot.id)
            snapshot_subdomain = get_snapshot_subdomain(snapshot_id)
            snapshot_host = get_snapshot_host(snapshot_id)
            original_host = get_original_host(snapshot.domain)
            web_host = get_web_host()
            host_only, port = split_host_port(SERVER_CONFIG.LISTEN_HOST)
            legacy_snapshot_host = f"{snapshot_id}.{host_only}"
            if port:
                legacy_snapshot_host = f"{legacy_snapshot_host}:{port}"

            client = Client()

            snapshot_path = f"/{snapshot.url_path}/"
            resp = client.get(snapshot_path, HTTP_HOST=web_host)
            assert resp.status_code == 200

            resp = client.get(f"/web/{snapshot.domain}", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"].endswith(f"/{snapshot.url_path}")

            resp = client.get(f"/{snapshot.url_path}", HTTP_HOST=web_host)
            assert resp.status_code == 200

            date_segment = snapshot.url_path.split("/")[1]
            resp = client.get(f"/web/{date_segment}/{date_segment}/{snapshot_id}/", HTTP_HOST=web_host)
            assert resp.status_code == 404

            resp = client.get(f"/{snapshot.url_path}/{output_rel}", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert snapshot_host in resp["Location"]

            resp = client.get("/", HTTP_HOST=legacy_snapshot_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"].startswith(f"http://{snapshot_host}")
            assert snapshot_subdomain in resp["Location"]

            resp = client.get(f"/{output_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert response_body(resp) == Path(snapshot.output_dir, output_rel).read_bytes()

            resp = client.get(f"/{response_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            snapshot_body = response_body(resp)
            if response_rel == "index.html":
                assert f"http://{snapshot_host}/".encode() in snapshot_body
                assert b"See all files..." in snapshot_body
            elif response_output_path.exists():
                assert snapshot_body == response_output_path.read_bytes()
            else:
                assert snapshot_body == response_file.read_bytes()

            resp = client.get(f"/{response_rel}", HTTP_HOST=original_host)
            assert resp.status_code == 200
            assert response_body(resp) == response_file.read_bytes()

            resp = client.get("/index.html", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            snapshot_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in snapshot_html
            assert "See all files..." in snapshot_html
            assert ">WARC<" not in snapshot_html
            assert ">Media<" not in snapshot_html
            assert ">Git<" not in snapshot_html

            resp = client.get("/?files=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            files_html = response_body(resp).decode("utf-8", "ignore")
            assert output_rel.split("/", 1)[0] in files_html

            resp = client.get("/?files=1&download=zip", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"] == "application/zip"
            assert ".zip" in resp["Content-Disposition"]
            assert resp.streaming
            with zipfile.ZipFile(io.BytesIO(response_body(resp))) as zip_file:
                assert any(name.endswith(f"/{output_rel}") for name in zip_file.namelist())

            output_dir = next((output.get("path", "").split("/", 1)[0] for output in snapshot.discover_outputs() if "/" in (output.get("path") or "")), None)
            assert output_dir is not None
            resp = client.get(f"/{output_dir}/", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            dir_html = response_body(resp).decode("utf-8", "ignore")
            assert f"Index of {output_dir}/" in dir_html

            print("OK")
            """,
        )

    def test_safe_subdomains_original_domain_host_uses_latest_matching_response(self) -> None:
        self._run(
            """
            from datetime import timedelta
            import shutil
            from django.utils import timezone
            from archivebox.crawls.models import Crawl

            snapshot = get_snapshot()
            original_host = get_original_host(snapshot.domain)
            client = Client()

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"

            now = timezone.now()
            created_by_id = snapshot.crawl.created_by_id
            created_snapshots = []
            created_crawls = []

            def make_snapshot(url):
                crawl = Crawl.objects.create(urls=url, created_by_id=created_by_id)
                created_crawls.append(crawl)
                snap = Snapshot.objects.create(url=url, crawl=crawl, status=Snapshot.StatusChoices.STARTED)
                created_snapshots.append(snap)
                return snap

            try:
                fixtures = (
                    (make_snapshot("https://example.com"), now + timedelta(minutes=1), "old root"),
                    (make_snapshot("https://example.com"), now + timedelta(minutes=2), "new root"),
                    (make_snapshot("https://example.com/about.html"), now + timedelta(minutes=3), "old about"),
                    (make_snapshot("https://example.com/about.html"), now + timedelta(minutes=4), "new about"),
                )

                for snap, stamp, content in fixtures:
                    snap.created_at = stamp
                    snap.bookmarked_at = stamp
                    snap.downloaded_at = stamp
                    snap.save(update_fields=["created_at", "bookmarked_at", "downloaded_at", "modified_at"])
                    responses_root = Path(snap.output_dir) / "responses" / snap.domain
                    responses_root.mkdir(parents=True, exist_ok=True)
                    rel_path = "about.html" if snap.url.endswith("/about.html") else "index.html"
                    (responses_root / rel_path).write_text(content, encoding="utf-8")

                resp = client.get("/", HTTP_HOST=original_host)
                assert resp.status_code == 200
                root_html = response_body(resp).decode("utf-8", "ignore")
                assert "new root" in root_html
                assert "old root" not in root_html

                resp = client.get("/about.html", HTTP_HOST=original_host)
                assert resp.status_code == 200
                about_html = response_body(resp).decode("utf-8", "ignore")
                assert "new about" in about_html
                assert "old about" not in about_html
            finally:
                for snap in created_snapshots:
                    shutil.rmtree(snap.output_dir, ignore_errors=True)
                for crawl in created_crawls:
                    crawl.delete()

            print("OK")
            """,
        )

    def test_safe_subdomains_original_domain_host_falls_back_to_latest_snapshot_live_page(self) -> None:
        self._run(
            """
            import shutil
            from django.utils import timezone
            from archivebox.crawls.models import Crawl

            snapshot = get_snapshot()
            fallback_domain = "fallback-original-host.example"
            original_host = get_original_host(fallback_domain)
            client = Client()

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"

            crawl = Crawl.objects.create(urls=f"https://{fallback_domain}", created_by_id=snapshot.crawl.created_by_id)
            latest_snapshot = Snapshot.objects.create(
                url=f"https://{fallback_domain}",
                crawl=crawl,
                status=Snapshot.StatusChoices.STARTED,
            )

            stamp = timezone.now()
            latest_snapshot.created_at = stamp
            latest_snapshot.bookmarked_at = stamp
            latest_snapshot.downloaded_at = stamp
            latest_snapshot.save(update_fields=["created_at", "bookmarked_at", "downloaded_at", "modified_at"])

            try:
                shutil.rmtree(Path(latest_snapshot.output_dir) / "responses", ignore_errors=True)

                resp = client.get("/", HTTP_HOST=original_host)
                assert resp.status_code == 200
                html = response_body(resp).decode("utf-8", "ignore")
                assert latest_snapshot.url in html
                assert f"http://{get_snapshot_host(str(latest_snapshot.id))}/" in html
            finally:
                shutil.rmtree(latest_snapshot.output_dir, ignore_errors=True)
                crawl.delete()

            print("OK")
            """,
        )

    def test_safe_subdomains_original_domain_host_redirects_to_save_page_now_when_missing_and_authenticated(self) -> None:
        self._run(
            """
            ensure_admin_user()
            client = Client()
            client.login(username="testadmin", password="testpassword")

            missing_domain = "missing-original-host.example"
            original_host = get_original_host(missing_domain)
            resp = client.get("/", HTTP_HOST=original_host)

            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{get_web_host()}/web/https://{missing_domain}"

            print("OK")
            """,
        )

    def test_safe_subdomains_fullreplay_leaves_risky_replay_unrestricted(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            dangerous_rel, safe_json_rel, sniffed_rel = write_replay_fixtures(snapshot)
            snapshot_host = get_snapshot_host(str(snapshot.id))

            client = Client()

            resp = client.get(f"/{dangerous_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

            resp = client.get(f"/{safe_json_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None

            resp = client.get(f"/{sniffed_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None

            print("OK")
            """,
        )

    def test_safe_onedomain_nojsreplay_routes_and_neuters_risky_documents(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            dangerous_rel, safe_json_rel, sniffed_rel = write_replay_fixtures(snapshot)
            snapshot_id = str(snapshot.id)

            client = Client()
            base_host = SERVER_CONFIG.LISTEN_HOST
            web_host = get_web_host()
            admin_host = get_admin_host()
            api_host = get_api_host()

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-onedomain-nojsreplay"
            assert web_host == base_host
            assert admin_host == base_host
            assert api_host == base_host
            assert get_snapshot_host(snapshot_id) == base_host
            assert get_original_host(snapshot.domain) == base_host
            assert get_listen_subdomain(base_host) == ""

            replay_url = build_snapshot_url(snapshot_id, dangerous_rel)
            assert replay_url == f"http://{base_host}/snapshot/{snapshot_id}/{dangerous_rel}"

            resp = client.get(f"/{snapshot.url_path}/{dangerous_rel}", HTTP_HOST=base_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == replay_url

            resp = client.get("/admin/login/", HTTP_HOST=base_host)
            assert resp.status_code == 200

            resp = client.get("/api/v1/docs", HTTP_HOST=base_host)
            assert resp.status_code == 200

            resp = client.get(f"/snapshot/{snapshot_id}/{dangerous_rel}", HTTP_HOST=base_host)
            assert resp.status_code == 200
            csp = resp.headers.get("Content-Security-Policy") or ""
            assert "sandbox" in csp
            assert "script-src 'none'" in csp
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

            resp = client.get(f"/snapshot/{snapshot_id}/{safe_json_rel}", HTTP_HOST=base_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

            resp = client.get("/snapshot/{}/singlefile/".format(snapshot_id), HTTP_HOST=base_host)
            assert resp.status_code == 404

            resp = client.get(f"/snapshot/{snapshot_id}/{sniffed_rel}", HTTP_HOST=base_host)
            assert resp.status_code == 200
            csp = resp.headers.get("Content-Security-Policy") or ""
            assert "sandbox" in csp
            assert "script-src 'none'" in csp

            print("OK")
            """,
            mode="safe-onedomain-nojsreplay",
        )

    def test_unsafe_onedomain_noadmin_blocks_control_plane_and_unsafe_methods(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            dangerous_rel, _, _ = write_replay_fixtures(snapshot)
            snapshot_id = str(snapshot.id)

            client = Client()
            base_host = SERVER_CONFIG.LISTEN_HOST

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "unsafe-onedomain-noadmin"
            assert SERVER_CONFIG.CONTROL_PLANE_ENABLED is False
            assert SERVER_CONFIG.BLOCK_UNSAFE_METHODS is True
            assert get_web_host() == base_host
            assert get_admin_host() == base_host
            assert get_api_host() == base_host

            for blocked_path in ("/admin/login/", "/api/v1/docs", "/add/", f"/web/{snapshot.domain}"):
                resp = client.get(blocked_path, HTTP_HOST=base_host)
                assert resp.status_code == 403, (blocked_path, resp.status_code)

            resp = client.post("/public/", data="x=1", content_type="application/x-www-form-urlencoded", HTTP_HOST=base_host)
            assert resp.status_code == 403

            resp = client.get(f"/snapshot/{snapshot_id}/{dangerous_rel}", HTTP_HOST=base_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

            print("OK")
            """,
            mode="unsafe-onedomain-noadmin",
        )

    def test_danger_onedomain_fullreplay_keeps_control_plane_and_raw_replay(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            dangerous_rel, _, _ = write_replay_fixtures(snapshot)
            snapshot_id = str(snapshot.id)

            client = Client()
            base_host = SERVER_CONFIG.LISTEN_HOST

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "danger-onedomain-fullreplay"
            assert SERVER_CONFIG.CONTROL_PLANE_ENABLED is True
            assert get_web_host() == base_host
            assert get_admin_host() == base_host
            assert get_api_host() == base_host
            assert build_snapshot_url(snapshot_id, dangerous_rel) == f"http://{base_host}/snapshot/{snapshot_id}/{dangerous_rel}"

            resp = client.get("/admin/login/", HTTP_HOST=base_host)
            assert resp.status_code == 200

            resp = client.get("/api/v1/docs", HTTP_HOST=base_host)
            assert resp.status_code == 200

            payload = '{"username": "testadmin", "password": "testpassword"}'
            resp = client.post(
                "/api/v1/auth/get_api_token",
                data=payload,
                content_type="application/json",
                HTTP_HOST=base_host,
            )
            assert resp.status_code == 200
            assert resp.json().get("token")

            resp = client.get(f"/snapshot/{snapshot_id}/{dangerous_rel}", HTTP_HOST=base_host)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Security-Policy") is None
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"

            print("OK")
            """,
            mode="danger-onedomain-fullreplay",
        )

    def test_onedomain_base_url_overrides_are_preserved_for_external_links(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            snapshot_id = str(snapshot.id)
            base_host = SERVER_CONFIG.LISTEN_HOST

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-onedomain-nojsreplay"
            assert get_admin_host() == base_host
            assert get_web_host() == base_host

            assert get_admin_base_url() == "https://admin.archivebox.example"
            assert get_web_base_url() == "https://archivebox.example"
            assert build_admin_url("/admin/login/") == "https://admin.archivebox.example/admin/login/"
            assert build_snapshot_url(snapshot_id, "index.jsonl") == (
                f"https://archivebox.example/snapshot/{snapshot_id}/index.jsonl"
            )

            print("OK")
            """,
            mode="safe-onedomain-nojsreplay",
            env_overrides={
                "ADMIN_BASE_URL": "https://admin.archivebox.example",
                "ARCHIVE_BASE_URL": "https://archivebox.example",
            },
        )

    def test_template_and_admin_links(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            snapshot.write_html_details()
            snapshot_id = str(snapshot.id)
            snapshot_host = get_snapshot_host(snapshot_id)
            admin_host = get_admin_host()
            web_host = get_web_host()
            public_host = get_public_host()

            client = Client()

            resp = client.get("/public/", HTTP_HOST=web_host)
            assert resp.status_code == 200
            public_html = response_body(resp).decode("utf-8", "ignore")
            assert "http://web.archivebox.localhost:8000" in public_html

            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=web_host)
            assert resp.status_code == 200
            live_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in live_html
            assert f"http://{public_host}/static/archive.png" in live_html
            assert "?preview=1" in live_html
            assert "function createMainFrame(previousFrame)" in live_html
            assert "function activateCardPreview(card, link)" in live_html
            assert "ensureMainFrame(true)" in live_html
            assert "previousFrame.parentNode.replaceChild(frame, previousFrame)" in live_html
            assert "previousFrame.src = 'about:blank'" in live_html
            assert "event.stopImmediatePropagation()" in live_html
            assert "const matchingLink = [...document.querySelectorAll('a[target=preview]')].find" in live_html
            assert "jQuery(link).click()" not in live_html
            assert "searchParams.delete('preview')" in live_html
            assert "doc.body.style.flexDirection = 'column'" in live_html
            assert "doc.body.style.alignItems = 'center'" in live_html
            assert "img.style.margin = '0 auto'" in live_html
            assert "window.location.hash = getPreviewHashValue(link)" in live_html
            assert "const selectedPreviewHash = decodeURIComponent(window.location.hash.slice(1)).toLowerCase()" in live_html
            assert "pointer-events: none;" in live_html
            assert "pointer-events: auto;" in live_html
            assert 'class="thumbnail-click-overlay"' in live_html
            assert "window.location.hash = getPreviewTypeFromPath(link)" not in live_html
            assert ">WARC<" not in live_html
            assert ">Media<" not in live_html
            assert ">Git<" not in live_html

            static_html = Path(snapshot.output_dir, "index.html").read_text(encoding="utf-8", errors="ignore")
            assert f"http://{snapshot_host}/" in static_html
            assert f"http://{public_host}/static/archive.png" in static_html
            assert "?preview=1" in static_html
            assert "function createMainFrame(previousFrame)" in static_html
            assert "function activateCardPreview(card, link)" in static_html
            assert "ensureMainFrame(true)" in static_html
            assert "previousFrame.parentNode.replaceChild(frame, previousFrame)" in static_html
            assert "previousFrame.src = 'about:blank'" in static_html
            assert "e.stopImmediatePropagation()" in static_html
            assert "const matchingLink = [...document.querySelectorAll('a[target=preview]')].find" in static_html
            assert "jQuery(link).click()" not in static_html
            assert "searchParams.delete('preview')" in static_html
            assert "doc.body.style.flexDirection = 'column'" in static_html
            assert "doc.body.style.alignItems = 'center'" in static_html
            assert "img.style.margin = '0 auto'" in static_html
            assert "window.location.hash = getPreviewHashValue(link)" in static_html
            assert "const selectedPreviewHash = decodeURIComponent(window.location.hash.slice(1)).toLowerCase()" in static_html
            assert "pointer-events: none;" in static_html
            assert "pointer-events: auto;" in static_html
            assert 'class="thumbnail-click-overlay"' in static_html
            assert "window.location.hash = getPreviewTypeFromPath(link)" not in static_html
            assert ">WARC<" not in static_html
            assert ">Media<" not in static_html
            assert ">Git<" not in static_html

            client.login(username="testadmin", password="testpassword")
            resp = client.get(f"/admin/core/snapshot/{snapshot_id}/change/", HTTP_HOST=admin_host)
            assert resp.status_code == 200
            admin_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://web.archivebox.localhost:8000/{snapshot.archive_path}" in admin_html
            assert f"http://{snapshot_host}/" in admin_html

            result = ArchiveResult.objects.filter(snapshot=snapshot).first()
            assert result is not None
            resp = client.get(f"/admin/core/archiveresult/{result.id}/change/", HTTP_HOST=admin_host)
            assert resp.status_code == 200
            ar_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in ar_html

            print("OK")
            """,
        )

    def test_snapshot_pages_preview_filesystem_text_outputs(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            web_host = get_web_host()

            consolelog_dir = Path(snapshot.output_dir) / "consolelog"
            consolelog_dir.mkdir(parents=True, exist_ok=True)
            (consolelog_dir / "console.jsonl").write_text(
                '{"level":"log","text":"console preview works"}\\n'
                '{"level":"warn","text":"second line"}\\n',
                encoding="utf-8",
            )

            client = Client()
            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=web_host)
            assert resp.status_code == 200
            live_html = response_body(resp).decode("utf-8", "ignore")
            assert 'data-plugin="consolelog" data-compact="1"' in live_html
            assert "console preview works" in live_html
            snapshot_host = get_snapshot_host(str(snapshot.id))
            resp = client.get("/consolelog/console.jsonl?preview=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("text/html")
            preview_html = response_body(resp).decode("utf-8", "ignore")
            assert "archivebox-text-preview" in preview_html
            assert "console preview works" in preview_html

            screenshot_dir = Path(snapshot.output_dir) / "screenshot"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            (screenshot_dir / "screenshot.png").write_bytes(
                bytes.fromhex(
                    "89504e470d0a1a0a"
                    "0000000d49484452000000010000000108060000001f15c489"
                    "0000000d49444154789c63f8ffffff7f0009fb03fd2a86e38a"
                    "0000000049454e44ae426082",
                ),
            )
            resp = client.get("/screenshot/screenshot.png?preview=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("text/html")

            print("OK")
            """,
        )

    def test_api_available_on_admin_and_api_hosts(self) -> None:
        self._run(
            """
            client = Client()
            admin_host = get_admin_host()
            api_host = get_api_host()

            resp = client.get("/api/v1/docs", HTTP_HOST=admin_host)
            assert resp.status_code == 200

            resp = client.get("/api/v1/docs", HTTP_HOST=api_host)
            assert resp.status_code == 200

            print("OK")
            """,
        )

    def test_api_auth_token_endpoint_available_on_admin_and_api_hosts(self) -> None:
        self._run(
            """
            ensure_admin_user()
            client = Client()
            admin_host = get_admin_host()
            api_host = get_api_host()

            payload = '{"username": "testadmin", "password": "testpassword"}'

            resp = client.post(
                "/api/v1/auth/get_api_token",
                data=payload,
                content_type="application/json",
                HTTP_HOST=admin_host,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("token")

            resp = client.post(
                "/api/v1/auth/get_api_token",
                data=payload,
                content_type="application/json",
                HTTP_HOST=api_host,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("token")

            print("OK")
            """,
        )

    def test_api_post_with_token_on_admin_and_api_hosts(self) -> None:
        self._run(
            """
            ensure_admin_user()
            from archivebox.api.auth import get_or_create_api_token

            token = get_or_create_api_token(get_user_model().objects.get(username="testadmin"))
            assert token is not None

            client = Client()
            admin_host = get_admin_host()
            api_host = get_api_host()

            payload = '{"name": "apitest-tag"}'
            headers = {"HTTP_X_ARCHIVEBOX_API_KEY": token.token}

            resp = client.post(
                "/api/v1/core/tags/create/",
                data=payload,
                content_type="application/json",
                HTTP_HOST=admin_host,
                **headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("success") is True
            assert data.get("tag_name") == "apitest-tag"

            resp = client.post(
                "/api/v1/core/tags/create/",
                data=payload,
                content_type="application/json",
                HTTP_HOST=api_host,
                **headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("success") is True
            assert data.get("tag_name") == "apitest-tag"

            print("OK")
            """,
        )
