#!/usr/bin/env python3
"""End-to-end tests for scheduling across CLI, server, API, and web UI."""

import os
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
