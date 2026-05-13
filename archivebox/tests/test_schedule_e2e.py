#!/usr/bin/env python3
"""End-to-end tests for scheduling across CLI, server, API, and web UI."""

import os
import re
import socket
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import requests

from .conftest import run_python_cwd


REPO_ROOT = Path(__file__).resolve().parents[2]


def init_archive(cwd: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "archivebox", "init", "--quick"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def build_test_env(port: int, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DATA_DIR", None)
    env.update(
        {
            "PLUGINS": "wget",
            "LISTEN_HOST": f"archivebox.localhost:{port}",
            "ALLOWED_HOSTS": "*",
            "CSRF_TRUSTED_ORIGINS": f"http://admin.archivebox.localhost:{port}",
            "PUBLIC_ADD_VIEW": "True",
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "TIMEOUT": "30",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "SAVE_ARCHIVEDOTORG": "False",
            "SAVE_TITLE": "False",
            "SAVE_FAVICON": "False",
            "SAVE_WARC": "False",
            "SAVE_PDF": "False",
            "SAVE_SCREENSHOT": "False",
            "SAVE_DOM": "False",
            "SAVE_SINGLEFILE": "False",
            "SAVE_READABILITY": "False",
            "SAVE_MERCURY": "False",
            "SAVE_GIT": "False",
            "SAVE_YTDLP": "False",
            "SAVE_HEADERS": "False",
            "SAVE_HTMLTOTEXT": "False",
            "SAVE_WGET": "True",
            "USE_CHROME": "False",
        },
    )
    env.update(extra)
    return env


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(cwd: Path, env: dict[str, str], port: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "archivebox", "server", "--daemonize", f"127.0.0.1:{port}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def stop_server(cwd: Path) -> None:
    script = textwrap.dedent(
        """
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()
        from archivebox.workers.supervisord_util import stop_existing_supervisord_process
        stop_existing_supervisord_process()
        print('stopped')
        """,
    )
    run_python_cwd(script, cwd=cwd, timeout=30)


def wait_for_http(port: int, host: str, path: str = "/", timeout: int = 30) -> requests.Response:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            response = requests.get(
                f"http://127.0.0.1:{port}{path}",
                headers={"Host": host},
                timeout=2,
                allow_redirects=False,
            )
            if response.status_code < 500:
                return response
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for HTTP on {host}: {last_exc}")


def make_latest_schedule_due(cwd: Path) -> None:
    conn = sqlite3.connect(cwd / "index.sqlite3")
    try:
        conn.execute(
            """
            UPDATE crawls_crawl
            SET created_at = datetime('now', '-2 day'),
                modified_at = datetime('now', '-2 day')
            WHERE id = (
                SELECT template_id
                FROM crawls_crawlschedule
                ORDER BY created_at DESC
                LIMIT 1
            )
            """,
        )
        conn.commit()
    finally:
        conn.close()


def get_snapshot_file_text(cwd: Path, url: str) -> str:
    script = textwrap.dedent(
        f"""
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(url={url!r}).order_by('-created_at').first()
        assert snapshot is not None, 'missing snapshot'
        assert snapshot.status == 'sealed', snapshot.status

        snapshot_dir = Path(snapshot.output_dir)
        candidates = []
        preferred_patterns = (
            'wget/**/index.html',
            'wget/**/*.html',
            'trafilatura/content.html',
            'trafilatura/content.txt',
            'defuddle/content.html',
            'defuddle/content.txt',
        )
        for pattern in preferred_patterns:
            for candidate in snapshot_dir.glob(pattern):
                if candidate.is_file():
                    candidates.append(candidate)

        if not candidates:
            for candidate in snapshot_dir.rglob('*'):
                if not candidate.is_file():
                    continue
                rel = candidate.relative_to(snapshot_dir)
                if rel.parts and rel.parts[0] == 'responses':
                    continue
                if candidate.suffix not in ('.html', '.htm', '.txt'):
                    continue
                if candidate.name in ('stdout.log', 'stderr.log', 'cmd.sh'):
                    continue
                candidates.append(candidate)

        assert candidates, f'no captured html/txt files found in {{snapshot_dir}}'
        print(candidates[0].read_text(errors='ignore'))
        """,
    )
    stdout, stderr, code = run_python_cwd(script, cwd=cwd, timeout=60)
    assert code == 0, stderr
    return stdout


def wait_for_snapshot_capture(cwd: Path, url: str, timeout: int = 180) -> str:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            return get_snapshot_file_text(cwd, url)
        except AssertionError as err:
            last_error = err
            time.sleep(2)
    raise AssertionError(f"timed out waiting for captured content for {url}: {last_error}")


def get_counts(cwd: Path, scheduled_url: str, one_shot_url: str) -> tuple[int, int, int]:
    conn = sqlite3.connect(cwd / "index.sqlite3")
    try:
        scheduled_snapshots = conn.execute(
            "SELECT COUNT(*) FROM core_snapshot WHERE url = ?",
            (scheduled_url,),
        ).fetchone()[0]
        one_shot_snapshots = conn.execute(
            "SELECT COUNT(*) FROM core_snapshot WHERE url = ?",
            (one_shot_url,),
        ).fetchone()[0]
        scheduled_crawls = conn.execute(
            """
            SELECT COUNT(*)
            FROM crawls_crawl
            WHERE schedule_id IS NOT NULL
              AND urls = ?
            """,
            (scheduled_url,),
        ).fetchone()[0]
        return scheduled_snapshots, one_shot_snapshots, scheduled_crawls
    finally:
        conn.close()


def get_depth_counts(cwd: Path) -> dict[int, int]:
    conn = sqlite3.connect(cwd / "index.sqlite3")
    try:
        return dict(conn.execute("SELECT depth, COUNT(*) FROM core_snapshot GROUP BY depth").fetchall())
    finally:
        conn.close()


def create_admin_and_token(cwd: Path) -> str:
    script = textwrap.dedent(
        """
        import os
        from datetime import timedelta
        from django.utils import timezone

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
        import django
        django.setup()

        from django.contrib.auth import get_user_model
        from archivebox.api.models import APIToken

        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username='apitestadmin',
            defaults={
                'email': 'apitestadmin@example.com',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password('testpass123')
        user.save()

        token = APIToken.objects.create(
            created_by=user,
            expires=timezone.now() + timedelta(days=1),
        )
        print(token.token)
        """,
    )
    stdout, stderr, code = run_python_cwd(script, cwd=cwd, timeout=60)
    assert code == 0, stderr
    return stdout.strip().splitlines()[-1]


@pytest.mark.timeout(180)
def test_server_processes_due_cli_schedule_and_saves_real_content(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port)

    schedule_result = subprocess.run(
        [sys.executable, "-m", "archivebox", "schedule", "--every=daily", "--depth=0", recursive_test_site["root_url"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert schedule_result.returncode == 0, schedule_result.stderr
    assert "Created scheduled crawl" in schedule_result.stdout

    make_latest_schedule_due(tmp_path)

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"web.archivebox.localhost:{port}")
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
        assert "About" in captured_text
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(180)
def test_archivebox_add_remains_one_shot_even_when_schedule_is_due(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port)
    scheduled_url = recursive_test_site["root_url"]
    one_shot_url = recursive_test_site["child_urls"][0]

    schedule_result = subprocess.run(
        [sys.executable, "-m", "archivebox", "schedule", "--every=daily", "--depth=0", scheduled_url],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert schedule_result.returncode == 0, schedule_result.stderr

    make_latest_schedule_due(tmp_path)

    add_result = subprocess.run(
        [sys.executable, "-m", "archivebox", "add", "--depth=0", "--plugins=wget", one_shot_url],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert add_result.returncode == 0, add_result.stderr
    captured_text = wait_for_snapshot_capture(tmp_path, one_shot_url, timeout=120)
    assert "Deep About" in captured_text or "About" in captured_text

    scheduled_snapshots, one_shot_snapshots, scheduled_crawls = get_counts(tmp_path, scheduled_url, one_shot_url)
    assert one_shot_snapshots >= 1
    assert scheduled_snapshots == 0
    assert scheduled_crawls == 1  # template only, no materialized scheduled run


@pytest.mark.timeout(180)
def test_schedule_rest_api_works_over_running_server(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port)
    api_token = create_admin_and_token(tmp_path)

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/schedule",
            headers={
                "Host": f"api.archivebox.localhost:{port}",
                "X-ArchiveBox-API-Key": api_token,
            },
            json={
                "every": "daily",
                "import_path": recursive_test_site["root_url"],
                "quiet": True,
            },
            timeout=10,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["success"] is True
        assert payload["result_format"] == "json"
        assert len(payload["result"]["created_schedule_ids"]) == 1
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(180)
def test_schedule_web_ui_post_works_over_running_server(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port, PUBLIC_ADD_VIEW="True")

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"web.archivebox.localhost:{port}", path="/add/")

        response = requests.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"web.archivebox.localhost:{port}"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "0",
                "schedule": "daily",
                "tag": "web-ui",
                "notes": "created from web ui",
            },
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code in (302, 303), response.text

        conn = sqlite3.connect(tmp_path / "index.sqlite3")
        try:
            row = conn.execute(
                """
                SELECT cs.schedule, c.urls, c.tags_str
                FROM crawls_crawlschedule cs
                JOIN crawls_crawl c ON c.schedule_id = cs.id
                ORDER BY cs.created_at DESC
                LIMIT 1
                """,
            ).fetchone()
        finally:
            conn.close()

        assert row == ("daily", recursive_test_site["root_url"], "web-ui")
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(240)
def test_web_ui_add_depth_two_crawls_and_renders_real_outputs_over_running_server(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(
        port,
        PLUGINS="wget,parse_html_urls",
        PUBLIC_INDEX="True",
        PUBLIC_ADD_VIEW="True",
    )
    create_admin_and_token(tmp_path)

    try:
        start_server(tmp_path, env=env, port=port)
        add_page = wait_for_http(port, host=f"web.archivebox.localhost:{port}", path="/add/")
        assert add_page.status_code == 200
        assert 'name="depth"' in add_page.text
        assert 'name="url"' in add_page.text

        response = requests.post(
            f"http://127.0.0.1:{port}/add/",
            headers={"Host": f"web.archivebox.localhost:{port}"},
            data={
                "url": recursive_test_site["root_url"],
                "depth": "2",
                "max_urls": "20",
                "max_size": "0",
                "archiving_plugins": ["wget"],
                "parsing_plugins": ["parse_html_urls"],
                "tag": "web-depth-two",
                "url_filters_allowlist": r"127\.0\.0\.1[:/].*",
                "url_filters_denylist": "",
                "schedule": "",
                "notes": "created from running-server web ui",
                "persona": "Default",
                "index_only": "",
                "config": "{}",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert response.status_code in (302, 303), response.text

        deadline = time.time() + 180
        while time.time() < deadline:
            depth_counts = get_depth_counts(tmp_path)
            if (
                depth_counts.get(0, 0) >= 1
                and depth_counts.get(1, 0) >= len(recursive_test_site["child_urls"])
                and depth_counts.get(2, 0) >= len(recursive_test_site["deep_urls"])
            ):
                break
            time.sleep(2)
        else:
            raise AssertionError(f"timed out waiting for depth=2 crawl, got depth counts {get_depth_counts(tmp_path)}")

        conn = sqlite3.connect(tmp_path / "index.sqlite3")
        try:
            depth_counts = dict(conn.execute("SELECT depth, COUNT(*) FROM core_snapshot GROUP BY depth").fetchall())
            crawl = conn.execute(
                "SELECT max_depth, max_urls, tags_str, notes FROM crawls_crawl ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            snapshot_rows = conn.execute(
                "SELECT url, depth, status, parent_snapshot_id FROM core_snapshot ORDER BY depth, url",
            ).fetchall()
            archive_results = conn.execute(
                "SELECT plugin, status, output_files, output_size FROM core_archiveresult ORDER BY plugin, status",
            ).fetchall()
        finally:
            conn.close()

        assert crawl == (2, 20, "web-depth-two", "created from running-server web ui")
        assert depth_counts.get(0, 0) >= 1
        assert depth_counts.get(1, 0) >= len(recursive_test_site["child_urls"])
        assert depth_counts.get(2, 0) >= len(recursive_test_site["deep_urls"])
        assert max(depth_counts) <= 2
        assert set(recursive_test_site["child_urls"]).issubset({url for url, depth, _status, _parent in snapshot_rows if depth == 1})
        assert set(recursive_test_site["deep_urls"]).issubset({url for url, depth, _status, _parent in snapshot_rows if depth == 2})

        result_statuses = [(plugin, status) for plugin, status, _files, _size in archive_results]
        assert ("wget", "succeeded") in result_statuses
        assert any(plugin.endswith("parse_html_urls") and status == "succeeded" for plugin, status in result_statuses)
        assert len([status for _plugin, status, _files, _size in archive_results if status == "failed"]) <= 2
        assert list((tmp_path / "users/system/snapshots").rglob("parse_html_urls/**/urls.jsonl"))
        assert list((tmp_path / "users/system/snapshots").rglob("wget/**/*.html"))

        progress = requests.get(
            f"http://127.0.0.1:{port}/admin/live-progress/",
            headers={"Host": f"admin.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert progress.status_code == 200
        assert "active_crawls" in progress.json()

        index_page = requests.get(
            f"http://127.0.0.1:{port}/",
            headers={"Host": f"web.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert index_page.status_code == 200
        assert recursive_test_site["root_url"] in index_page.text

        session = requests.Session()
        login_page = session.get(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": f"admin.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert login_page.status_code == 200
        csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
        assert csrf_match, login_page.text[:500]
        login_response = session.post(
            f"http://127.0.0.1:{port}/admin/login/",
            headers={"Host": f"admin.archivebox.localhost:{port}", "Referer": f"http://admin.archivebox.localhost:{port}/admin/login/"},
            data={
                "username": "apitestadmin",
                "password": "testpass123",
                "csrfmiddlewaretoken": csrf_match.group(1),
                "next": "/admin/",
            },
            timeout=10,
            allow_redirects=False,
        )
        assert login_response.status_code in (302, 303), login_response.text
        snapshot_admin = session.get(
            f"http://127.0.0.1:{port}/admin/core/snapshot/",
            headers={"Host": f"admin.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert snapshot_admin.status_code == 200
        assert recursive_test_site["root_url"] in snapshot_admin.text
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(180)
def test_core_rest_api_crud_uses_token_auth_and_persists_side_effects_over_running_server(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port, PUBLIC_INDEX="True")
    api_token = create_admin_and_token(tmp_path)
    api_headers = {
        "Host": f"api.archivebox.localhost:{port}",
        "X-ArchiveBox-API-Key": api_token,
    }

    try:
        start_server(tmp_path, env=env, port=port)
        docs = wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")
        assert docs.status_code == 200
        openapi = wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/openapi.json")
        assert openapi.status_code == 200
        paths = openapi.json()["paths"]
        assert "/api/v1/core/snapshots" in paths
        assert "/api/v1/crawls/crawls" in paths

        unauth = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers={"Host": f"api.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert unauth.status_code in (401, 403)
        bad_auth = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers={"Host": f"api.archivebox.localhost:{port}", "X-ArchiveBox-API-Key": "bad-token"},
            timeout=10,
        )
        assert bad_auth.status_code in (401, 403)

        crawl_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers=api_headers,
            json={
                "urls": [recursive_test_site["root_url"]],
                "max_depth": 2,
                "max_urls": 7,
                "max_size": 0,
                "tags": ["api-depth-two"],
                "label": "api crawl",
                "notes": "created through REST API",
                "config": {"PLUGINS": "wget,parse_html_urls", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
            timeout=10,
        )
        assert crawl_response.status_code == 200, crawl_response.text
        crawl_payload = crawl_response.json()
        crawl_id = crawl_payload["id"]
        assert crawl_payload["max_depth"] == 2
        assert crawl_payload["max_urls"] == 7
        assert crawl_payload["tags_str"] == "api-depth-two"
        assert crawl_payload["config"]["PLUGINS"] == "wget,parse_html_urls"

        snapshot_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/core/snapshots",
            headers=api_headers,
            json={
                "url": recursive_test_site["child_urls"][0],
                "crawl_id": crawl_id,
                "depth": 1,
                "title": "API child snapshot",
                "tags": ["api-child"],
                "status": "queued",
            },
            timeout=10,
        )
        assert snapshot_response.status_code == 200, snapshot_response.text
        snapshot_payload = snapshot_response.json()
        snapshot_id = snapshot_payload["id"]
        assert snapshot_payload["url"] == recursive_test_site["child_urls"][0]
        assert snapshot_payload["tags"] == ["api-child"]

        patch_snapshot = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/core/snapshot/{snapshot_id}",
            headers=api_headers,
            json={"status": "sealed", "tags": ["api-child", "api-patched"]},
            timeout=10,
        )
        assert patch_snapshot.status_code == 200, patch_snapshot.text
        assert patch_snapshot.json()["status"] == "sealed"
        assert set(patch_snapshot.json()["tags"]) == {"api-child", "api-patched"}

        tag_create = requests.post(
            f"http://127.0.0.1:{port}/api/v1/core/tags/create/",
            headers=api_headers,
            json={"name": "api-extra"},
            timeout=10,
        )
        assert tag_create.status_code == 200, tag_create.text
        tag_id = tag_create.json()["tag_id"]

        add_tag = requests.post(
            f"http://127.0.0.1:{port}/api/v1/core/tags/add-to-snapshot/",
            headers=api_headers,
            json={"snapshot_id": snapshot_id, "tag_id": tag_id},
            timeout=10,
        )
        assert add_tag.status_code == 200, add_tag.text
        remove_tag = requests.post(
            f"http://127.0.0.1:{port}/api/v1/core/tags/remove-from-snapshot/",
            headers=api_headers,
            json={"snapshot_id": snapshot_id, "tag_name": "api-extra"},
            timeout=10,
        )
        assert remove_tag.status_code == 200, remove_tag.text

        crawl_patch = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
            json={"status": "sealed", "tags": ["api-sealed"]},
            timeout=10,
        )
        assert crawl_patch.status_code == 200, crawl_patch.text
        assert crawl_patch.json()["status"] == "sealed"
        assert crawl_patch.json()["tags_str"] == "api-sealed"

        snapshots_list = requests.get(
            f"http://127.0.0.1:{port}/api/v1/core/snapshots?tag=api-patched&with_archiveresults=true",
            headers=api_headers,
            timeout=10,
        )
        assert snapshots_list.status_code == 200, snapshots_list.text
        snapshot_items = snapshots_list.json()["items"]
        assert len(snapshot_items) == 1
        assert snapshot_items[0]["id"] == snapshot_id
        assert snapshot_items[0]["archiveresults"] == []

        bearer_response = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers={"Host": f"api.archivebox.localhost:{port}", "Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        assert bearer_response.status_code == 200, bearer_response.text
        query_response = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}?api_key={api_token}",
            headers={"Host": f"api.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert query_response.status_code == 200, query_response.text

        delete_snapshot = requests.delete(
            f"http://127.0.0.1:{port}/api/v1/core/snapshot/{snapshot_id}",
            headers=api_headers,
            timeout=10,
        )
        assert delete_snapshot.status_code == 200, delete_snapshot.text
        assert delete_snapshot.json()["success"] is True

        delete_crawl = requests.delete(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
            timeout=10,
        )
        assert delete_crawl.status_code == 200, delete_crawl.text
        assert delete_crawl.json()["success"] is True

        conn = sqlite3.connect(tmp_path / "index.sqlite3")
        try:
            assert conn.execute("SELECT COUNT(*) FROM crawls_crawl WHERE id = ?", (crawl_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM core_snapshot WHERE id = ?", (snapshot_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM core_tag WHERE name = 'api-extra'").fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(180)
def test_cli_rest_api_add_search_update_remove_over_running_server(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port, PUBLIC_INDEX="True")
    api_token = create_admin_and_token(tmp_path)
    api_headers = {
        "Host": f"api.archivebox.localhost:{port}",
        "X-ArchiveBox-API-Key": api_token,
    }

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        add_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/add",
            headers=api_headers,
            json={
                "urls": [recursive_test_site["root_url"]],
                "tag": "api-cli",
                "depth": 1,
                "parser": "url_list",
                "plugins": "wget",
                "update": True,
                "overwrite": False,
                "index_only": True,
            },
            timeout=10,
        )
        assert add_response.status_code == 200, add_response.text
        add_payload = add_response.json()
        assert add_payload["success"] is True
        assert add_payload["result_format"] == "json"
        assert add_payload["result"]["num_snapshots"] == 1
        crawl_id = add_payload["result"]["crawl_id"]
        snapshot_id = add_payload["result"]["snapshot_ids"][0]

        search_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/search",
            headers=api_headers,
            json={
                "filter_patterns": [recursive_test_site["root_url"]],
                "filter_type": "exact",
                "status": "indexed",
                "sort": "bookmarked_at",
                "as_json": True,
                "as_html": False,
                "as_csv": "",
                "with_headers": False,
            },
            timeout=10,
        )
        assert search_response.status_code == 200, search_response.text
        search_payload = search_response.json()
        assert search_payload["success"] is True
        assert search_payload["result_format"] == "json"
        assert any(item["url"] == recursive_test_site["root_url"] for item in search_payload["result"])

        update_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/update",
            headers=api_headers,
            json={
                "resume": None,
                "after": 0,
                "before": 4102444800,
                "filter_type": "exact",
                "filter_patterns": [recursive_test_site["root_url"]],
                "batch_size": 1,
                "continuous": False,
            },
            timeout=20,
        )
        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["success"] is True

        conn = sqlite3.connect(tmp_path / "index.sqlite3")
        try:
            crawl = conn.execute(
                "SELECT max_depth, tags_str, config FROM crawls_crawl WHERE id IN (?, ?)",
                (crawl_id, crawl_id.replace("-", "")),
            ).fetchone()
        finally:
            conn.close()

        assert crawl is not None
        assert crawl[0] == 1
        assert crawl[1] == "api-cli"
        assert '"INDEX_ONLY": true' in crawl[2] or '"INDEX_ONLY":true' in crawl[2]

        remove_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/remove",
            headers=api_headers,
            json={
                "delete": True,
                "after": 0,
                "before": 4102444800,
                "filter_type": "exact",
                "filter_patterns": [recursive_test_site["root_url"]],
            },
            timeout=20,
        )
        assert remove_response.status_code == 200, remove_response.text
        remove_payload = remove_response.json()
        assert remove_payload["success"] is True
        assert remove_payload["result"]["removed_count"] == 1
        assert snapshot_id in remove_payload["result"]["removed_snapshot_ids"]

        conn = sqlite3.connect(tmp_path / "index.sqlite3")
        try:
            snapshot_count = conn.execute("SELECT COUNT(*) FROM core_snapshot WHERE id = ?", (snapshot_id,)).fetchone()[0]
        finally:
            conn.close()

        assert snapshot_count == 0
    finally:
        stop_server(tmp_path)
