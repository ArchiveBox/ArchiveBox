import os
import subprocess
import sys
import textwrap
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from archivebox.tests.conftest import run_archivebox_cmd

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.django_db
def test_archiveresult_relpath_uses_sibling_hook_that_owns_output(admin_user):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.core.views import _resolve_archiveresult_relpath
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com", crawl=crawl)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        hook_name="on_Snapshot__archivebox_browser_extension_upload",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={"browser.png": {"size": 7}},
    )
    server_result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        hook_name="on_Snapshot__50_screenshot",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={"screenshot.png": {"size": 6, "root_relative": True}},
    )

    resolved_path, result = _resolve_archiveresult_relpath(snapshot, "screenshot/screenshot.png")

    assert resolved_path == "screenshot.png"
    assert result == server_result


def test_html_image_sources_rewrite_to_captured_responses(tmp_path):
    from archivebox.misc.serve_static import _rewrite_html_image_sources_to_responses

    responses_dir = tmp_path / "responses" / "all"
    responses_dir.mkdir(parents=True)
    local_image = responses_dir / "20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png"
    remote_image = responses_dir / "20260722T061544__GET__https_3A_2F_2Fa.sweeting.me_2Fmatomo.php_3Fidsite_3D1_26rec_3D1_.gif"
    local_image.write_bytes(b"png")
    remote_image.write_bytes(b"gif")

    rewritten, count = _rewrite_html_image_sources_to_responses(
        (
            '<img src="images/twitter.png">'
            '<img width="48" src="images/twitter.png">'
            '<img src="https://a.sweeting.me/matomo.php?idsite=1&rec=1">'
        ),
        tmp_path,
        "extractor/content.html",
        "https://sweeting.me/",
    )

    assert count == 3
    local_src = 'src="../responses/all/20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png"'
    assert rewritten.count(local_src) == 2
    assert 'src="../responses/all/20260722T061544__GET__https_3A_2F_2Fa.sweeting.me_2Fmatomo.php_3Fidsite_3D1_26rec_3D1_.gif"' in rewritten

    rewritten_root, root_count = _rewrite_html_image_sources_to_responses(
        '<img src="images/twitter.png">',
        tmp_path,
        "index.html",
        "https://sweeting.me/",
    )

    assert root_count == 1
    assert 'src="responses/all/20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png"' in rewritten_root


def test_html_image_response_index_preserves_first_image_and_last_fallback(tmp_path):
    from archivebox.misc.serve_static import _encoded_responses_image_url, _index_responses_paths_for_html_images

    responses_dir = tmp_path / "responses" / "all"
    responses_dir.mkdir(parents=True)
    encoded_image = _encoded_responses_image_url("image", "https://example.com/")
    encoded_fallback = _encoded_responses_image_url("document", "https://example.com/")
    assert encoded_image and encoded_fallback

    (responses_dir / f"1__GET__{encoded_image}.txt").write_text("fallback", encoding="utf-8")
    first_image = responses_dir / f"2__GET__{encoded_image}.png"
    first_image.write_bytes(b"first")
    (responses_dir / f"3__GET__{encoded_image}.jpg").write_bytes(b"later")
    (responses_dir / f"1__GET__{encoded_fallback}.txt").write_text("first", encoding="utf-8")
    last_fallback = responses_dir / f"2__GET__{encoded_fallback}.bin"
    last_fallback.write_bytes(b"last")

    response_paths = _index_responses_paths_for_html_images(
        tmp_path,
        "extractor/content.html",
        {encoded_image, encoded_fallback},
    )

    image_candidates = [path for path in responses_dir.rglob(f"*__GET__{encoded_image}*") if path.is_file()]
    expected_image = next(
        path for path in image_candidates if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
    )
    fallback_candidates = [path for path in responses_dir.rglob(f"*__GET__{encoded_fallback}*") if path.is_file()]
    expected_fallback = fallback_candidates[-1]

    assert first_image in image_candidates
    assert last_fallback in fallback_candidates
    assert response_paths[encoded_image] == "../" + expected_image.relative_to(tmp_path).as_posix()
    assert response_paths[encoded_fallback] == "../" + expected_fallback.relative_to(tmp_path).as_posix()


def test_static_html_and_markdown_preview_images_rewrite_to_captured_responses(tmp_path):
    from django.test import RequestFactory

    from archivebox.misc.serve_static import serve_static_with_byterange_support

    responses_dir = tmp_path / "responses" / "all"
    responses_dir.mkdir(parents=True)
    (responses_dir / "20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png").write_bytes(b"png")

    html_path = tmp_path / "extractor" / "content.html"
    html_path.parent.mkdir()
    html_path.write_text('<img src="images/twitter.png"><img width="48" src="images/twitter.png">', encoding="utf-8")

    request = RequestFactory().get("/web/20260722/sweeting.me/snapshot/extractor/content.html")
    request.archivebox_snapshot_url = "https://sweeting.me/"

    response = serve_static_with_byterange_support(request, "extractor/content.html", document_root=tmp_path)

    assert response.status_code == 200
    assert "ETag" not in response.headers
    assert "max-age=60" in response.headers["Cache-Control"]
    assert b"archivebox-static-html-preview-style" in response.content
    assert b"width: min(100%, 72rem)" in response.content
    assert b"min-height: 100vh" in response.content
    assert b"img:not([width]):not([height])" in response.content
    assert b"a > img:not([width]):not([height])" in response.content
    assert b'src="../responses/all/20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png"' in response.content
    assert (
        b'<img width="48" src="../responses/all/20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png">'
        in response.content
    )

    text_path = tmp_path / "article" / "content.txt"
    text_path.parent.mkdir()
    text_path.write_text(
        "# Title\n\n"
        "![Twitter](images/twitter.png)\n\n"
        "- One\n"
        "- Two\n"
        "- Three\n"
        "[A](https://example.com) [B](https://example.com/b) [C](https://example.com/c)\n",
        encoding="utf-8",
    )

    request = RequestFactory().get("/web/20260722/sweeting.me/snapshot/article/content.txt")
    request.archivebox_snapshot_url = "https://sweeting.me/"

    response = serve_static_with_byterange_support(request, "article/content.txt", document_root=tmp_path)

    assert response.status_code == 200
    assert "ETag" not in response.headers
    assert "max-age=60" in response.headers["Cache-Control"]
    assert b"archivebox-static-html-preview-style" in response.content
    assert b"width: min(100%, 72rem)" in response.content
    assert b"min-height: 100vh" in response.content
    assert b'src="../responses/all/20260722T061544__GET__https_3A_2F_2Fsweeting.me_2Fimages_2Ftwitter.png"' in response.content


@pytest.fixture
def checked_in_static_site():
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


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
        check=False,
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
    from archivebox.config.common import get_config
    SERVER_CONFIG = get_config()
    from archivebox.core.routes_util import (
        get_admin_host,
        get_admin_base_url,
        get_base_host,
        get_api_host,
        get_web_host,
        get_web_base_url,
        get_snapshot_subdomain,
        get_snapshot_host,
        get_original_host,
        get_listen_subdomain,
        split_host_port,
        host_matches,
        is_snapshot_subdomain,
        build_admin_url,
        build_snapshot_url,
        build_original_url,
    )
    from archivebox.core.middleware import ADMIN_LOGIN_HINT_COOKIE

    def response_body(resp):
        if resp.streaming:
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

        responses_root = Path(snapshot.output_dir) / "responses"
        assert responses_root.exists()
        response_file = None
        response_rel = None
        for candidate in responses_root.rglob("*"):
            if not candidate.is_file():
                continue
            if snapshot.domain not in candidate.relative_to(responses_root).parts:
                continue
            rel = candidate.relative_to(snapshot.output_dir)
            if str(rel) in reserved_snapshot_paths:
                continue
            response_file = candidate
            response_rel = str(rel)
            break
        if response_file is None:
            for candidate in responses_root.rglob("*"):
                if not candidate.is_file():
                    continue
                if snapshot.domain not in candidate.relative_to(responses_root).parts:
                    continue
                rel = candidate.relative_to(snapshot.output_dir)
                if str(rel) in reserved_snapshot_paths:
                    continue
                response_file = candidate
                response_rel = str(rel)
                break
        if response_file is None:
            response_file = next(p for p in responses_root.rglob("*") if p.is_file())
            response_rel = str(response_file.relative_to(snapshot.output_dir))
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
        responses_root = Path(snapshot.output_dir) / "responses" / "text" / snapshot.domain
        responses_root.mkdir(parents=True, exist_ok=True)
        sniffed_response = responses_root / "dangerous-response"
        sniffed_response.write_text(
            "<!doctype html><html><body><script>window.__archivebox_response__ = true;</script><p>Response Danger</p></body></html>",
            encoding="utf-8",
        )
        return "dangerous.html", "safe.json", str(sniffed_response.relative_to(snapshot.output_dir))
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

    def _set_config(self, *settings: str) -> None:
        result = run_archivebox_cmd(["config", "--set", *settings], cwd=self.data_dir)
        assert result.returncode == 0, result.stderr

    def _install_archivewebpage_extension(self, lib_dir: Path) -> Path:
        extensions_dir = lib_dir / "chromewebstore" / "extensions"
        result = run_archivebox_cmd(
            ["install", "archivewebpage"],
            cwd=self.data_dir,
            timeout=600,
            env={
                "ABXPKG_LIB_DIR": str(lib_dir),
                "CHROMEWEBSTORE_EXTENSIONS_DIR": str(extensions_dir),
                "SHOW_PROGRESS": "False",
                "USE_COLOR": "False",
            },
        )
        assert result.returncode == 0, result.stderr or result.stdout
        installed = list(extensions_dir.glob("*__archivewebpage"))
        assert len(installed) == 1, installed
        assert (installed[0] / "ui.js").is_file()
        assert (installed[0] / "sw.js").is_file()
        return installed[0]

    @pytest.mark.parametrize(
        "mode",
        ["auto", "safe-subdomains-fullreplay", "safe-onedomain-nojsreplay", "unsafe-onedomain-noadmin", "danger-onedomain-fullreplay"],
    )
    def test_snapshot_output_delete_handoff_is_non_mutating_in_every_security_mode(self, mode: str) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
            snapshot.save(update_fields=["config"])
            plugin = "security_delete_test"
            output_path = Path(snapshot.output_dir) / plugin / "output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("security test", encoding="utf-8")
            result, _ = ArchiveResult.objects.update_or_create(
                snapshot=snapshot,
                plugin=plugin,
                defaults={
                    "hook_name": "on_Snapshot__99_security_delete_test.py",
                    "status": ArchiveResult.StatusChoices.SUCCEEDED,
                    "output_str": "output.txt",
                    "output_files": {"output.txt": {"size": 13, "mimetype": "text/plain"}},
                    "output_size": 13,
                },
            )

            client = Client(enforce_csrf_checks=True)
            assert client.login(username="testadmin", password="testpassword")
            admin_host = get_admin_host()
            admin_page = client.get("/admin/", HTTP_HOST=admin_host)
            if SERVER_CONFIG.CONTROL_PLANE_ENABLED:
                assert admin_page.status_code == 200
            else:
                assert admin_page.status_code == 403
            assert admin_page["X-Frame-Options"] == "DENY"
            assert "frame-ancestors 'none'" in admin_page["Content-Security-Policy"]

            snapshot_host = get_snapshot_host(str(snapshot.id)) if SERVER_CONFIG.USES_SUBDOMAIN_ROUTING else get_base_host()
            snapshot_path = "/index.html" if SERVER_CONFIG.USES_SUBDOMAIN_ROUTING else f"/snapshot/{snapshot.id}/index.html"
            detail = client.get(snapshot_path, HTTP_HOST=snapshot_host)
            html = response_body(detail).decode("utf-8", "ignore")

            assert detail.status_code == 200, (detail.status_code, detail.headers.get("Location"), html[:200])
            assert "delete-output-csrf" not in html
            if SERVER_CONFIG.CONTROL_PLANE_ENABLED:
                assert f'data-archive-result-ids="{result.id}"' in html, html[-1000:]
                assert 'data-delete-handoff="1"' in html, html[-1000:]
            else:
                assert f'data-archive-result-ids="{result.id}"' not in html

            rejected = client.post(
                "/admin/core/archiveresult/",
                data={"action": "delete_selected", "post": "yes", "_selected_action": str(result.id)},
                HTTP_HOST=snapshot_host,
            )
            assert rejected.status_code == 403, (rejected.status_code, rejected.headers.get("Location"), response_body(rejected)[:200])
            assert ArchiveResult.objects.filter(pk=result.pk).exists()
            result.delete()
            print("OK")
            """,
            mode=mode,
        )

    def test_cross_domain_admin_hint_only_marks_superusers(self) -> None:
        self._run(
            """
            User = get_user_model()
            staff = User.objects.create_user(username="staff-hint-test", password="testpassword", is_staff=True)
            client = Client()
            client.force_login(staff)
            response = client.get("/admin/", HTTP_HOST=get_admin_host())
            assert response.status_code == 200
            assert client.cookies.get(ADMIN_LOGIN_HINT_COOKIE) is None or client.cookies[ADMIN_LOGIN_HINT_COOKIE].value != "1"

            client.force_login(ensure_admin_user())
            response = client.get("/admin/", HTTP_HOST=get_admin_host())
            assert response.status_code == 200
            assert client.cookies[ADMIN_LOGIN_HINT_COOKIE].value == "1"
            print("OK")
            """,
            mode="safe-subdomains-fullreplay",
        )

    def test_routes_util_and_web_public_redirect(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            snapshot_id = str(snapshot.id)
            domain = snapshot.domain

            web_host = get_web_host()
            admin_host = get_admin_host()
            api_host = get_api_host()
            snapshot_subdomain = get_snapshot_subdomain(snapshot_id)
            snapshot_host = get_snapshot_host(snapshot_id)
            original_host = get_original_host(domain)
            bind_addr = SERVER_CONFIG.BIND_ADDR
            base_host = get_base_host()

            bind_host, bind_port = split_host_port(bind_addr)
            assert bind_host == "127.0.0.1"
            assert bind_port == "8000"
            host_only, port = split_host_port(base_host)
            assert host_only == "archivebox.localhost"
            assert port == "8000"
            assert web_host == "web.archivebox.localhost:8000"
            assert admin_host == "admin.archivebox.localhost:8000"
            assert api_host == "api.archivebox.localhost:8000"
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

            resp = client.get("/api/archive/https://example.com/", HTTP_HOST=api_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{web_host}/web/https://example.com/"

            print("OK")
            """,
        )

    def test_api_archive_redirect_uses_web_base_url(self) -> None:
        try:
            config_result = run_archivebox_cmd(
                ["config", "--set", "BASE_URL=https://archivebox.io"],
                cwd=self.data_dir,
            )
            assert config_result.returncode == 0, config_result.stderr
            self._run(
                """
                client = Client()

                resp = client.get(
                    "/api/archive/https://example.com/",
                    HTTP_HOST="api.archivebox.io",
                    secure=True,
                )

                assert resp.status_code in (301, 302)
                assert resp["Location"] == "https://web.archivebox.io/web/https://example.com/"

                print("OK")
                """,
                mode="safe-subdomains-fullreplay",
            )
        finally:
            reset_result = run_archivebox_cmd(
                ["config", "--set", "BASE_URL=http://archivebox.localhost:8000"],
                cwd=self.data_dir,
            )
            assert reset_result.returncode == 0, reset_result.stderr

    def test_web_admin_routing(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            client = Client()
            web_host = get_web_host()
            admin_host = get_admin_host()
            snapshot_host = get_snapshot_host(str(snapshot.id))
            original_host = get_original_host(snapshot.domain)

            resp = client.get("/admin/login/", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert admin_host in resp["Location"]

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

            for control_host in (admin_host, web_host):
                resp = client.get(f"/snapshot/{snapshot.id}/index.jsonl?download=1", HTTP_HOST=control_host)
                assert resp.status_code in (301, 302)
                assert resp["Location"] == f"http://{snapshot_host}/index.jsonl?download=1"

                resp = client.get(f"/original/{snapshot.domain}/index.html", HTTP_HOST=control_host)
                assert resp.status_code in (301, 302)
                assert resp["Location"] == f"http://{snapshot_host}/responses/{snapshot.domain}/index.html"

            resp = client.get("/static/jquery.min.js", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert "javascript" in (resp.headers.get("Content-Type") or "")

            resp = client.get("/static/jquery.min.js", HTTP_HOST=original_host)
            assert resp.status_code == 200
            assert "javascript" in (resp.headers.get("Content-Type") or "")

            print("OK")
            """,
        )

    def test_admin_login_next_allows_archivebox_hosts_only(self) -> None:
        self._run(
            """
            ensure_admin_user()
            snapshot = get_snapshot()
            admin_host = get_admin_host()
            web_host = get_web_host()
            api_host = get_api_host()
            snapshot_id = str(snapshot.id)

            allowed_next_urls = [
                "/admin/core/snapshot/",
                f"http://archivebox.localhost:8000/public/",
                f"http://{web_host}/public/",
                f"http://{admin_host}/admin/core/snapshot/",
                f"http://{api_host}/api/v1/docs",
                build_snapshot_url(snapshot_id, "index.html"),
                build_original_url(snapshot.domain, "index.html"),
            ]
            for next_url in allowed_next_urls:
                client = Client()
                resp = client.post(
                    "/admin/login/",
                    data={"username": "testadmin", "password": "testpassword", "next": next_url},
                    HTTP_HOST=admin_host,
                )
                assert resp.status_code in (301, 302), (next_url, resp.status_code, response_body(resp)[:500])
                assert resp["Location"] == next_url, (next_url, resp["Location"])

            blocked_next_urls = [
                "https://anything.attacker.com/admin/",
                "//anything.attacker.com/admin/",
                "https://archivebox.localhost.attacker.com/public/",
                "http://web.archivebox.localhost:9999/public/",
                "javascript:alert(1)",
            ]
            for next_url in blocked_next_urls:
                client = Client()
                resp = client.post(
                    "/admin/login/",
                    data={"username": "testadmin", "password": "testpassword", "next": next_url},
                    HTTP_HOST=admin_host,
                )
                assert resp.status_code in (301, 302), (next_url, resp.status_code, response_body(resp)[:500])
                assert resp["Location"] == "/admin/", (next_url, resp["Location"])
                assert "attacker.com" not in resp["Location"]

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
            host_only, port = split_host_port(get_base_host())
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

            original_response_rel = response_rel.split(f"responses/{snapshot.domain}/", 1)[-1]
            resp = client.get(f"/{original_response_rel}", HTTP_HOST=original_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == f"http://{snapshot_host}/responses/{snapshot.domain}/{original_response_rel}"
            resp = client.get(f"/responses/{snapshot.domain}/{original_response_rel}", HTTP_HOST=snapshot_host)
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
            from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
            from django.core import signing
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            from django.utils import timezone
            from archivebox.crawls.models import Crawl
            from archivebox.core.views import REPLAY_AUTH_SALT, _replay_cookie_name

            snapshot = get_snapshot()
            original_host = get_original_host(snapshot.domain)
            client = Client()

            assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"

            now = timezone.now()
            created_by_id = snapshot.crawl.created_by_id
            created_snapshots = []
            created_crawls = []
            real_output_files = sorted({
                Path(result.output_dir) / relative_path
                for result in ArchiveResult.objects.filter(snapshot=snapshot)
                for relative_path in (result.output_files or {})
                if (Path(result.output_dir) / relative_path).is_file()
            })
            assert len(real_output_files) >= 4, real_output_files
            real_output_bodies = [path.read_bytes() for path in real_output_files[:4]]
            assert len(set(real_output_bodies)) == 4

            def make_snapshot(url, permissions="public"):
                crawl = Crawl.objects.create(urls=url, created_by_id=created_by_id)
                created_crawls.append(crawl)
                snap = Snapshot.objects.create(
                    url=url,
                    crawl=crawl,
                    status=Snapshot.StatusChoices.STARTED,
                    config={"PERMISSIONS": permissions},
                )
                created_snapshots.append(snap)
                return snap

            try:
                fixtures = (
                    (make_snapshot("https://example.com"), now + timedelta(minutes=1), real_output_bodies[0]),
                    (make_snapshot("https://example.com"), now + timedelta(minutes=2), real_output_bodies[1]),
                    (make_snapshot("https://example.com/about.html"), now + timedelta(minutes=3), real_output_bodies[2]),
                    (make_snapshot("https://example.com/about.html"), now + timedelta(minutes=4), real_output_bodies[3]),
                    (make_snapshot("https://example.com/about.html", permissions="private"), now + timedelta(minutes=5), b"private"),
                    (make_snapshot("https://example.com.evil/about.html"), now + timedelta(minutes=6), b"wrong-domain"),
                )

                for snap, stamp, content in fixtures:
                    snap.created_at = stamp
                    snap.bookmarked_at = stamp
                    snap.downloaded_at = stamp
                    snap.save(update_fields=["created_at", "bookmarked_at", "downloaded_at", "modified_at"])
                    responses_root = Path(snap.output_dir) / "responses" / snap.domain
                    responses_root.mkdir(parents=True, exist_ok=True)
                    rel_path = "about.html" if snap.url.endswith("/about.html") else "index.html"
                    (responses_root / rel_path).write_bytes(content)

                with CaptureQueriesContext(connection) as root_queries:
                    resp = client.get("/", HTTP_HOST=original_host)
                assert resp.status_code in (301, 302)
                assert resp["Location"] == f"http://{get_snapshot_host(str(fixtures[1][0].id))}/responses/example.com/index.html"
                root_snapshot_queries = [
                    query["sql"] for query in root_queries.captured_queries
                    if 'FROM "core_snapshot"' in query["sql"] and query["sql"].lstrip().upper().startswith("SELECT")
                ]
                assert len(root_snapshot_queries) == 1, root_snapshot_queries

                with CaptureQueriesContext(connection) as path_queries:
                    resp = client.get("/about.html", HTTP_HOST=original_host)
                assert resp.status_code in (301, 302)
                assert resp["Location"] == f"http://{get_snapshot_host(str(fixtures[3][0].id))}/responses/example.com/about.html"
                path_snapshot_queries = [
                    query["sql"] for query in path_queries.captured_queries
                    if 'FROM "core_snapshot"' in query["sql"] and query["sql"].lstrip().upper().startswith("SELECT")
                ]
                assert len(path_snapshot_queries) == 1, path_snapshot_queries

                ensure_admin_user()
                auth_client = Client()
                assert auth_client.login(username="testadmin", password="testpassword")
                session = auth_client.session
                private_snapshot = fixtures[4][0]
                replay_client = Client()
                replay_client.cookies[_replay_cookie_name(private_snapshot)] = signing.dumps(
                    {
                        "snapshot_id": str(private_snapshot.id),
                        "session_key": session.session_key,
                        "user_id": str(session[SESSION_KEY]),
                        "auth_hash": str(session[HASH_SESSION_KEY]),
                    },
                    salt=REPLAY_AUTH_SALT,
                )
                replay_resp = replay_client.get("/about.html", HTTP_HOST=original_host)
                assert replay_resp.status_code in (301, 302)
                assert replay_resp["Location"] == f"http://{get_snapshot_host(str(private_snapshot.id))}/responses/example.com/about.html"
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
                assert resp.status_code in (301, 302)
                assert resp["Location"] == f"http://{get_snapshot_host(str(latest_snapshot.id))}"
                resp = client.get("/", HTTP_HOST=get_snapshot_host(str(latest_snapshot.id)))
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

    def test_safe_onedomain_original_domain_replay_keeps_path_fallback_priority(self) -> None:
        self._run(
            """
            from datetime import timedelta
            import shutil
            from django.contrib.auth.models import AnonymousUser
            from django.db import connection
            from django.test import RequestFactory
            from django.test.utils import CaptureQueriesContext
            from django.utils import timezone
            from archivebox.crawls.models import Crawl
            from archivebox.core.views import OriginalDomainHostView

            seed = get_snapshot()
            domain = "onedomain-response.example"
            created_crawls = []
            created_snapshots = []
            now = timezone.now()

            def make_snapshot(url, stamp):
                crawl = Crawl.objects.create(urls=url, created_by_id=seed.crawl.created_by_id)
                created_crawls.append(crawl)
                snap = Snapshot.objects.create(
                    url=url,
                    crawl=crawl,
                    status=Snapshot.StatusChoices.STARTED,
                    config={"PERMISSIONS": "public"},
                )
                snap.created_at = stamp
                snap.bookmarked_at = stamp
                snap.downloaded_at = stamp
                snap.save(update_fields=["created_at", "bookmarked_at", "downloaded_at", "modified_at"])
                created_snapshots.append(snap)
                return snap

            try:
                index_snapshot = make_snapshot(f"https://{domain}/docs", now + timedelta(minutes=1))
                html_snapshot = make_snapshot(f"https://{domain}/docs", now + timedelta(minutes=2))
                index_path = Path(index_snapshot.output_dir) / "responses" / domain / "docs" / "index.html"
                html_path = Path(html_snapshot.output_dir) / "responses" / domain / "docs.html"
                index_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_bytes(b"index-fallback")
                html_path.write_bytes(b"html-fallback")

                assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-onedomain-nojsreplay"
                request = RequestFactory().get("/docs", HTTP_HOST=get_base_host())
                request.user = AnonymousUser()
                request.archivebox_config = SERVER_CONFIG
                with CaptureQueriesContext(connection) as queries:
                    response = OriginalDomainHostView.as_view()(request, domain=domain, path="docs")

                assert response.status_code == 200
                assert response_body(response) == b"index-fallback"
                snapshot_queries = [
                    query["sql"] for query in queries.captured_queries
                    if 'FROM "core_snapshot"' in query["sql"] and query["sql"].lstrip().upper().startswith("SELECT")
                ]
                assert len(snapshot_queries) == 1, snapshot_queries
            finally:
                for snap in created_snapshots:
                    shutil.rmtree(snap.output_dir, ignore_errors=True)
                for crawl in created_crawls:
                    crawl.delete()

            print("OK")
            """,
            mode="safe-onedomain-nojsreplay",
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
            base_host = get_base_host()
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
            base_host = get_base_host()

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
            base_host = get_base_host()

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

    def test_default_base_url_preserves_runtime_listen_port(self) -> None:
        try:
            self._set_config("BIND_ADDR=127.0.0.1:8766", "BASE_URL=")
            self._run(
                """
                client = Client()

                assert get_admin_host() == "admin.archivebox.localhost:8766"
                assert get_web_host() == "web.archivebox.localhost:8766"
                assert build_admin_url("/admin/") == "http://admin.archivebox.localhost:8766/admin/"

                resp = client.get("/admin/login/", HTTP_HOST="127.0.0.1:8766")
                assert resp.status_code == 200

                print("OK")
                """,
                mode="safe-subdomains-fullreplay",
            )
        finally:
            self._set_config("BIND_ADDR=127.0.0.1:8000", "BASE_URL=http://archivebox.localhost:8000")

    def test_subdomain_replay_assets_route_without_base_url(self) -> None:
        lib_dir = self.data_dir / "test-lib"
        self._install_archivewebpage_extension(lib_dir)
        try:
            self._set_config("BIND_ADDR=127.0.0.1:8766", "BASE_URL=")
            self._run(
                """
                snapshot = get_snapshot()
                snapshot_host = get_snapshot_host(str(snapshot.id))
                extensions_dir = Path(SERVER_CONFIG.ABXPKG_LIB_DIR) / "chromewebstore" / "extensions"
                extension_dir = next(extensions_dir.glob("*__archivewebpage"))

                client = Client()
                resp = client.get("/replay/ui.js", HTTP_HOST=snapshot_host)
                body = response_body(resp)

                assert resp.status_code == 200
                assert resp["Content-Type"].startswith("application/javascript")
                assert body == (extension_dir / "ui.js").read_bytes()

                print("OK")
                """,
                mode="safe-subdomains-fullreplay",
                env_overrides={"ABXPKG_LIB_DIR": str(lib_dir)},
            )
        finally:
            self._set_config("BIND_ADDR=127.0.0.1:8000", "BASE_URL=http://archivebox.localhost:8000")

    def test_subdomain_replay_assets_use_derived_chromewebstore_extensions_dir(self) -> None:
        lib_dir = self.data_dir / "test-lib"
        self._install_archivewebpage_extension(lib_dir)
        try:
            self._set_config("BIND_ADDR=127.0.0.1:8766", "BASE_URL=")
            self._run(
                """
                snapshot = get_snapshot()
                snapshot_host = get_snapshot_host(str(snapshot.id))
                expected_extensions_dir = Path(SERVER_CONFIG.ABXPKG_LIB_DIR) / "chromewebstore" / "extensions"

                extension_dir = next(expected_extensions_dir.glob("*__archivewebpage"))

                client = Client()
                resp = client.get("/replay/ui.js", HTTP_HOST=snapshot_host)
                body = response_body(resp)

                assert resp.status_code == 200
                assert resp["Content-Type"].startswith("application/javascript")
                assert body == (extension_dir / "ui.js").read_bytes()

                print("OK")
                """,
                mode="safe-subdomains-fullreplay",
                env_overrides={"ABXPKG_LIB_DIR": str(lib_dir)},
            )
        finally:
            self._set_config("BIND_ADDR=127.0.0.1:8000", "BASE_URL=http://archivebox.localhost:8000")

    def test_onedomain_base_url_overrides_are_preserved_for_external_links(self) -> None:
        try:
            self._set_config("BASE_URL=https://archivebox.example")
            self._run(
                """
                snapshot = get_snapshot()
                snapshot_id = str(snapshot.id)
                base_host = get_base_host()

                assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-onedomain-nojsreplay"
                assert get_admin_host() == base_host
                assert get_web_host() == base_host

                assert get_admin_base_url() == "https://archivebox.example"
                assert get_web_base_url() == "https://archivebox.example"
                assert build_admin_url("/admin/login/") == "https://archivebox.example/admin/login/"
                assert build_snapshot_url(snapshot_id, "index.jsonl") == (
                    f"https://archivebox.example/snapshot/{snapshot_id}/index.jsonl"
                )

                print("OK")
                """,
                mode="safe-onedomain-nojsreplay",
            )
        finally:
            self._set_config("BASE_URL=http://archivebox.localhost:8000")

    def test_subdomain_snapshot_urls_inherit_https_archive_base_url(self) -> None:
        try:
            self._set_config("BASE_URL=https://archivebox.example")
            self._run(
                """
                snapshot = get_snapshot()
                snapshot_id = str(snapshot.id)
                snapshot_host = get_snapshot_host(snapshot_id)

                assert SERVER_CONFIG.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"
                assert get_web_base_url() == "https://web.archivebox.example"
                assert build_snapshot_url(snapshot_id, "index.html") == f"https://{snapshot_host}/index.html"
                assert build_original_url("example.com", "index.html") == "https://web.archivebox.example/original/example.com/index.html"

                print("OK")
                """,
                mode="safe-subdomains-fullreplay",
            )
        finally:
            self._set_config("BASE_URL=http://archivebox.localhost:8000")

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

            client = Client()

            resp = client.get("/public/", HTTP_HOST=web_host)
            assert resp.status_code == 200
            public_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in public_html

            ensure_admin_user()
            assert client.login(username="testadmin", password="testpassword")

            resp = client.get("/public/", HTTP_HOST=web_host)
            assert resp.status_code == 200
            assert not getattr(resp.wsgi_request.user, "is_authenticated", False)

            resp = client.get("/admin/", HTTP_HOST=admin_host)
            assert resp.status_code == 200
            assert client.cookies[ADMIN_LOGIN_HINT_COOKIE].value == "1"

            resp = client.get("/public/", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert resp["Location"] == "http://admin.archivebox.localhost:8000/admin/core/snapshot/"

            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=web_host)
            assert resp.status_code == 200
            live_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in live_html
            assert f"http://{web_host}/static/archive.png" in live_html
            assert "?preview=1" in live_html
            assert "function createMainFrame(previousFrame)" in live_html
            assert "function activateCardPreview(card, link, updateHash=true)" in live_html
            assert "ensureMainFrame(currentSrc !== nextSrcAbs)" in live_html
            assert "previousFrame.parentNode.replaceChild(frame, previousFrame)" in live_html
            assert "previousFrame.src = 'about:blank'" in live_html
            assert "event.stopImmediatePropagation()" in live_html
            assert "const matchingLink = findPreviewLinkForHash(selectedPreviewHash)" in live_html
            assert "jQuery(link).click()" not in live_html
            assert "searchParams.delete('preview')" in live_html
            assert "doc.body.style.flexDirection = 'column'" in live_html
            assert "doc.body.style.alignItems = 'center'" in live_html
            assert "img.style.margin = '0 auto'" in live_html
            assert "window.location.hash = getPreviewHashValueFromHref(rawTarget)" in live_html
            assert "const selectedPreviewHash = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)).toLowerCase() : ''" in live_html
            assert "pointer-events: none;" in live_html
            assert "pointer-events: auto;" in live_html
            assert 'class="thumbnail-click-overlay"' in live_html
            assert "window.location.hash = getPreviewTypeFromPath(link)" not in live_html
            assert ">WARC<" not in live_html
            assert ">Media<" not in live_html
            assert ">Git<" not in live_html

            static_html = Path(snapshot.output_dir, "index.html").read_text(encoding="utf-8", errors="ignore")
            assert f"http://{snapshot_host}/" not in static_html
            assert f"http://{web_host}/static/archive.png" not in static_html
            # Static pages are opened directly from disk or a plain HTTP server,
            # where Django's live-only ?files=1 directory browser does not exist.
            # Even hidden controls and JavaScript fallbacks must therefore use
            # portable files, or an offline click can silently navigate nowhere.
            assert "?files=1" not in static_html
            assert "data:image/svg+xml" in static_html
            assert 'href="./' in static_html
            assert "?preview=1" in static_html
            assert "function createMainFrame(previousFrame)" in static_html
            assert "function activateCardPreview(card, link, updateHash=true)" in static_html
            assert "ensureMainFrame(currentSrc !== nextSrcAbs)" in static_html
            assert "previousFrame.parentNode.replaceChild(frame, previousFrame)" in static_html
            assert "previousFrame.src = 'about:blank'" in static_html
            assert "event.stopImmediatePropagation()" in static_html
            assert "const matchingLink = findPreviewLinkForHash(selectedPreviewHash)" in static_html
            assert "jQuery(link).click()" not in static_html
            assert "searchParams.delete('preview')" in static_html
            assert "doc.body.style.flexDirection = 'column'" in static_html
            assert "doc.body.style.alignItems = 'center'" in static_html
            assert "img.style.margin = '0 auto'" in static_html
            assert "window.location.hash = getPreviewHashValueFromHref(rawTarget)" in static_html
            assert "const selectedPreviewHash = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)).toLowerCase() : ''" in static_html
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
            assert f"http://{web_host}/{snapshot.archive_path}" in admin_html
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

    def test_snapshot_pages_preview_filesystem_text_outputs(self, checked_in_static_site) -> None:
        console_marker = "archivebox-consolelog-preview-fixture"
        console_source_url = f"{checked_in_static_site}/archivebox/tests/fixtures/consolelog_preview.html"
        capture = run_archivebox_cmd(
            [
                "add",
                "--depth=0",
                "--plugins=consolelog,screenshot,chrome_mhtml",
                console_source_url,
            ],
            cwd=self.data_dir,
            timeout=600,
            env={"SHOW_PROGRESS": "False", "USE_COLOR": "False"},
        )
        assert capture.returncode == 0, capture.stderr or capture.stdout
        self._run(
            """
            snapshot = get_snapshot()
            web_host = get_web_host()
            consolelog_dir = Path(snapshot.output_dir) / "consolelog"
            consolelog_file = next(path for path in consolelog_dir.rglob("*.jsonl") if path.is_file())
            consolelog_text = consolelog_file.read_text(encoding="utf-8")
            assert consolelog_text.strip()
            assert "__CONSOLE_MARKER__" in consolelog_text
            console_result = ArchiveResult.objects.get(snapshot=snapshot, plugin="consolelog")
            assert consolelog_file.name in console_result.output_files
            snapshot.write_html_details()

            client = Client()
            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=web_host)
            assert resp.status_code == 200
            live_html = response_body(resp).decode("utf-8", "ignore")
            assert 'data-plugin="consolelog" data-compact="1"' in live_html
            snapshot_host = get_snapshot_host(str(snapshot.id))
            consolelog_rel = consolelog_file.relative_to(snapshot.output_dir)
            resp = client.get(f"/{consolelog_rel}?preview=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("text/html")
            preview_html = response_body(resp).decode("utf-8", "ignore")
            assert "archivebox-text-preview" in preview_html
            import html, json
            first_console_record = json.loads(consolelog_text.splitlines()[0])
            assert html.escape(first_console_record["text"]) in preview_html
            assert "__CONSOLE_MARKER__" in preview_html

            screenshot_dir = Path(snapshot.output_dir) / "screenshot"
            screenshot_file = next(path for path in screenshot_dir.rglob("*.png") if path.is_file())
            screenshot_rel = screenshot_file.relative_to(snapshot.output_dir)
            resp = client.get(f"/{screenshot_rel}?preview=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("text/html")

            root_screenshot = screenshot_file.read_bytes()
            import shutil
            shutil.copyfile(screenshot_file, Path(snapshot.output_dir) / "screenshot.png")
            ArchiveResult.objects.update_or_create(
                snapshot=snapshot,
                plugin="screenshot",
                defaults={
                    "status": ArchiveResult.StatusChoices.SUCCEEDED,
                    "output_files": {"screenshot.png": {"size": len(root_screenshot), "root_relative": True}},
                    "output_str": "screenshot.png",
                },
            )
            resp = client.get("/screenshot/screenshot.png", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("image/png")
            assert response_body(resp) == root_screenshot

            mhtml_dir = Path(snapshot.output_dir) / "chrome_mhtml"
            mhtml_file = next(path for path in mhtml_dir.rglob("*.mhtml") if path.is_file())
            mhtml_rel = mhtml_file.relative_to(snapshot.output_dir)
            resp = client.get(f"/{mhtml_rel}?preview=1", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert resp["Content-Type"].startswith("text/html")
            assert "style-src 'unsafe-inline' data: blob:" in resp["Content-Security-Policy"]
            preview_html = response_body(resp).decode("utf-8", "ignore")
            assert "MHTML Preview" in preview_html

            print("OK")
            """.replace("__CONSOLE_MARKER__", console_marker),
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
