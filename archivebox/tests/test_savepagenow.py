"""Integration tests for /web/https://... shortcut (Save Page Now)."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from archivebox.tests.conftest import create_test_url


ADMIN_HOST = "admin.archivebox.localhost:8000"


def _run_savepagenow_script(
    initialized_archive: Path,
    request_url: str,
    expected_url: str,
    *,
    login: bool,
    public_add_view: bool,
    host: str,
):
    script = textwrap.dedent(
        f"""
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')

        from archivebox.config.django import setup_django
        setup_django()

        from django.test import Client
        from django.contrib.auth import get_user_model
        from archivebox.core.models import Snapshot

        client = Client()
        if {login!r}:
            user = get_user_model().objects.create_user(username='tester', password='pw')
            client.force_login(user)

        target_url = {request_url!r}

        resp = client.get('/web/' + target_url, HTTP_HOST={host!r})
        assert resp.status_code == 302, resp.status_code

        snapshot = Snapshot.objects.filter(url={expected_url!r}).order_by('-created_at').first()
        if snapshot is None:
            raise AssertionError(
                "snapshot not created; status=%s location=%s count=%s"
                % (
                    resp.status_code,
                    resp.get('Location'),
                    Snapshot.objects.count(),
                )
            )
        assert resp['Location'] == f"/{{snapshot.url_path}}"

        resp2 = client.get('/web/' + target_url, HTTP_HOST={host!r})
        assert resp2.status_code == 302, resp2.status_code
        assert Snapshot.objects.filter(url={expected_url!r}).count() == 1
        assert resp2['Location'] == f"/{{snapshot.url_path}}"
        """,
    )

    env = {
        **os.environ,
        "DATA_DIR": str(initialized_archive),
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
        "PUBLIC_ADD_VIEW": "True" if public_add_view else "False",
        "SAVE_ARCHIVEDOTORG": "False",
        "SAVE_TITLE": "False",
        "SAVE_FAVICON": "False",
        "SAVE_WGET": "False",
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
    }

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=initialized_archive,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _run_savepagenow_not_found_script(initialized_archive: Path, request_url: str):
    script = textwrap.dedent(
        f"""
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')

        from archivebox.config.django import setup_django
        setup_django()

        from django.test import Client
        from archivebox.core.models import Snapshot

        client = Client()
        target_url = {request_url!r}

        resp = client.get('/web/' + target_url, HTTP_HOST='web.archivebox.localhost:8000')
        assert resp.status_code == 302, resp.status_code
        assert resp['Location'] == f'http://{ADMIN_HOST}/web/' + target_url
        assert Snapshot.objects.count() == 0
        """,
    )

    env = {
        **os.environ,
        "DATA_DIR": str(initialized_archive),
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
        "PUBLIC_ADD_VIEW": "False",
        "SAVE_ARCHIVEDOTORG": "False",
        "SAVE_TITLE": "False",
        "SAVE_FAVICON": "False",
        "SAVE_WGET": "False",
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
    }

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=initialized_archive,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _run_savepagenow_via_web_host_redirect_script(initialized_archive: Path, request_url: str, expected_url: str):
    script = textwrap.dedent(
        f"""
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')

        from archivebox.config.django import setup_django
        setup_django()

        from django.test import Client
        from django.contrib.auth import get_user_model
        from archivebox.core.models import Snapshot

        client = Client()
        user = get_user_model().objects.create_user(username='tester', password='pw')
        client.force_login(user)

        target_url = {request_url!r}

        resp = client.get('/web/' + target_url, HTTP_HOST='web.archivebox.localhost:8000')
        assert resp.status_code == 302, resp.status_code
        assert resp['Location'] == f'http://{ADMIN_HOST}/web/' + target_url

        resp2 = client.get('/web/' + target_url, HTTP_HOST={ADMIN_HOST!r})
        assert resp2.status_code == 302, resp2.status_code

        snapshot = Snapshot.objects.filter(url={expected_url!r}).order_by('-created_at').first()
        assert snapshot is not None
        assert resp2['Location'] == f"/{{snapshot.url_path}}"
        assert Snapshot.objects.filter(url={expected_url!r}).count() == 1
        """,
    )

    env = {
        **os.environ,
        "DATA_DIR": str(initialized_archive),
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
        "PUBLIC_ADD_VIEW": "False",
        "SAVE_ARCHIVEDOTORG": "False",
        "SAVE_TITLE": "False",
        "SAVE_FAVICON": "False",
        "SAVE_WGET": "False",
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
    }

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=initialized_archive,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _run_savepagenow_existing_snapshot_script(initialized_archive: Path, request_url: str, stored_url: str):
    script = textwrap.dedent(
        f"""
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')

        from archivebox.config.django import setup_django
        setup_django()

        from django.test import Client
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.base_models.models import get_or_create_system_user_pk

        target_url = {request_url!r}
        stored_url = {stored_url!r}
        created_by_id = get_or_create_system_user_pk()
        crawl = Crawl.objects.create(urls=stored_url, created_by_id=created_by_id)
        snapshot = Snapshot.objects.create(url=stored_url, crawl=crawl)

        client = Client()
        resp = client.get('/web/' + target_url, HTTP_HOST='web.archivebox.localhost:8000')
        assert resp.status_code == 302, resp.status_code
        assert resp['Location'] == f"/{{snapshot.url_path}}"
        """,
    )

    env = {
        **os.environ,
        "DATA_DIR": str(initialized_archive),
        "USE_COLOR": "False",
        "SHOW_PROGRESS": "False",
        "PUBLIC_ADD_VIEW": "False",
        "SAVE_ARCHIVEDOTORG": "False",
        "SAVE_TITLE": "False",
        "SAVE_FAVICON": "False",
        "SAVE_WGET": "False",
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
    }

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=initialized_archive,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_web_add_creates_and_reuses_snapshot_logged_in(initialized_archive):
    """/web/https://... should work for authenticated users even when public add is off."""
    url = create_test_url(domain="example.com", path="savepagenow-auth")
    request_url = url.replace("https://", "")
    result = _run_savepagenow_script(initialized_archive, request_url, url, login=True, public_add_view=False, host=ADMIN_HOST)
    assert result.returncode == 0, f"SavePageNow shortcut (logged-in) test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_web_add_creates_and_reuses_snapshot_public(initialized_archive):
    """/web/https://... should work when PUBLIC_ADD_VIEW is enabled without login."""
    url = create_test_url(domain="example.com", path="savepagenow-public")
    request_url = url
    result = _run_savepagenow_script(
        initialized_archive,
        request_url,
        url,
        login=False,
        public_add_view=True,
        host="web.archivebox.localhost:8000",
    )
    assert result.returncode == 0, f"SavePageNow shortcut (public add) test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_web_add_requires_login_when_public_off(initialized_archive):
    """/web/https://... should bounce to admin when PUBLIC_ADD_VIEW is false and not logged in."""
    url = create_test_url(domain="example.com", path="savepagenow-404")
    request_url = url
    result = _run_savepagenow_not_found_script(initialized_archive, request_url)
    assert result.returncode == 0, f"SavePageNow shortcut (no public add) test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_web_add_redirects_to_admin_and_creates_when_logged_in(initialized_archive):
    """/web/https://... on web host should redirect to admin host and create when the user is logged in there."""
    url = create_test_url(domain="example.com", path="savepagenow-web-admin")
    result = _run_savepagenow_via_web_host_redirect_script(initialized_archive, url, url)
    assert result.returncode == 0, (
        f"SavePageNow shortcut (web->admin redirect) test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_web_add_redirects_existing_snapshot_when_public_off(initialized_archive):
    """/web/https://... should redirect to existing snapshot even when public add is off and not logged in."""
    url = create_test_url(domain="example.com", path="savepagenow-existing")
    request_url = url.replace("https://", "")
    result = _run_savepagenow_existing_snapshot_script(initialized_archive, request_url, url)
    assert result.returncode == 0, (
        f"SavePageNow shortcut (existing snapshot) test failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
