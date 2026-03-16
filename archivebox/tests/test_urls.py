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


def _run_python(script: str, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    env = _merge_pythonpath(os.environ.copy())
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
        get_api_host,
        get_web_host,
        get_snapshot_host,
        get_original_host,
        get_listen_subdomain,
        split_host_port,
        host_matches,
        is_snapshot_subdomain,
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
        assert snapshot is not None
        return snapshot

    def get_snapshot_files(snapshot):
        output_rel = None
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
            if not (Path(snapshot.output_dir) / rel).exists():
                response_file = candidate
                response_rel = str(rel)
                break
        if response_file is None:
            response_file = next(p for p in responses_root.rglob("*") if p.is_file())
            response_rel = str(response_file.relative_to(responses_root))
        response_output_path = Path(snapshot.output_dir) / response_rel
        return output_rel, response_file, response_rel, response_output_path
    """
    )
    return prelude + "\n" + textwrap.dedent(body)


@pytest.mark.usefixtures("real_archive_with_example")
class TestUrlRouting:
    data_dir: Path

    def _run(self, body: str, timeout: int = 120) -> None:
        script = _build_script(body)
        result = _run_python(script, cwd=self.data_dir, timeout=timeout)
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
            snapshot_host = get_snapshot_host(snapshot_id)
            original_host = get_original_host(domain)
            base_host = SERVER_CONFIG.LISTEN_HOST

            host_only, port = split_host_port(base_host)
            assert host_only == "archivebox.localhost"
            assert port == "8000"
            assert web_host == "web.archivebox.localhost:8000"
            assert admin_host == "admin.archivebox.localhost:8000"
            assert api_host == "api.archivebox.localhost:8000"
            assert snapshot_host == f"{snapshot_id}.archivebox.localhost:8000"
            assert original_host == f"{domain}.archivebox.localhost:8000"
            assert get_listen_subdomain(web_host) == "web"
            assert get_listen_subdomain(admin_host) == "admin"
            assert get_listen_subdomain(api_host) == "api"
            assert get_listen_subdomain(snapshot_host) == snapshot_id
            assert get_listen_subdomain(original_host) == domain
            assert get_listen_subdomain(base_host) == ""
            assert host_matches(web_host, get_web_host())
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
            """
        )

    def test_web_admin_routing(self) -> None:
        self._run(
            """
            ensure_admin_user()
            client = Client()
            web_host = get_web_host()
            admin_host = get_admin_host()

            resp = client.get("/add/", HTTP_HOST=web_host)
            assert resp.status_code == 200

            resp = client.get("/admin/login/", HTTP_HOST=web_host)
            assert resp.status_code in (301, 302)
            assert admin_host in resp["Location"]

            resp = client.get("/admin/login/", HTTP_HOST=admin_host)
            assert resp.status_code == 200

            print("OK")
            """
        )

    def test_snapshot_routing_and_hosts(self) -> None:
        self._run(
            """
            snapshot = get_snapshot()
            output_rel, response_file, response_rel, response_output_path = get_snapshot_files(snapshot)
            snapshot_id = str(snapshot.id)
            snapshot_host = get_snapshot_host(snapshot_id)
            original_host = get_original_host(snapshot.domain)
            web_host = get_web_host()

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

            resp = client.get(f"/{output_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            assert response_body(resp) == Path(snapshot.output_dir, output_rel).read_bytes()

            resp = client.get(f"/{response_rel}", HTTP_HOST=snapshot_host)
            assert resp.status_code == 200
            snapshot_body = response_body(resp)
            if response_output_path.exists():
                assert snapshot_body == response_output_path.read_bytes()
            else:
                assert snapshot_body == response_file.read_bytes()

            resp = client.get(f"/{response_rel}", HTTP_HOST=original_host)
            assert resp.status_code == 200
            assert response_body(resp) == response_file.read_bytes()

            print("OK")
            """
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

            client = Client()

            resp = client.get("/public/", HTTP_HOST=web_host)
            assert resp.status_code == 200
            public_html = response_body(resp).decode("utf-8", "ignore")
            assert "http://web.archivebox.localhost:8000" in public_html

            resp = client.get(f"/{snapshot.url_path}/index.html", HTTP_HOST=web_host)
            assert resp.status_code == 200
            live_html = response_body(resp).decode("utf-8", "ignore")
            assert f"http://{snapshot_host}/" in live_html
            assert "http://web.archivebox.localhost:8000" in live_html

            static_html = Path(snapshot.output_dir, "index.html").read_text(encoding="utf-8", errors="ignore")
            assert f"http://{snapshot_host}/" in static_html

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
            """
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
            """
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
            """
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
            """
        )
