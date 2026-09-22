"""Snapshot model and admin UI tests."""

import json
import os
import re
import shutil
import warnings
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.paginator import UnorderedObjectListWarning
from django.test import Client, RequestFactory
from django.urls import reverse

from archivebox.core.middleware import ADMIN_LOGIN_HINT_COOKIE
from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook

pytestmark = pytest.mark.django_db(transaction=True)
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_current_snapshot_layout_has_no_top_level_timestamp_projection(snapshot):
    from archivebox.config import CONSTANTS

    legacy_path = CONSTANTS.ARCHIVE_DIR / snapshot.timestamp

    assert Path(snapshot.output_dir).is_relative_to(CONSTANTS.ARCHIVE_DIR / "users")
    assert not legacy_path.exists()
    assert not legacy_path.is_symlink()


@pytest.fixture
def real_hash_projection(snapshot, cached_abxpkg_lib_dir):
    snapshot.output_dir.mkdir(parents=True, exist_ok=True)
    (snapshot.output_dir / "source.txt").write_text("real snapshot admin input", encoding="utf-8")
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=cached_abxpkg_lib_dir,
    )


@pytest.fixture
def real_failed_title_projection(snapshot, cached_abxpkg_lib_dir):
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        lib_dir=cached_abxpkg_lib_dir,
        expected_exit_codes=(1,),
    )


@pytest.fixture
def real_noresults_projection(snapshot, cached_abxpkg_lib_dir):
    staticfile_dir = snapshot.output_dir / "staticfile"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("plain text without links", encoding="utf-8")
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="parse_txt_urls",
        hook_name="on_Snapshot__71_parse_txt_urls.py",
        lib_dir=cached_abxpkg_lib_dir,
    )


@pytest.fixture
def real_parse_projection(snapshot, cached_abxpkg_lib_dir):
    staticfile_dir = snapshot.output_dir / "staticfile"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("https://example.org/parsed\n", encoding="utf-8")
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="parse_txt_urls",
        hook_name="on_Snapshot__71_parse_txt_urls.py",
        lib_dir=cached_abxpkg_lib_dir,
    )


@pytest.fixture
def running_wget_projection(snapshot, blocking_http_server):
    from django.utils import timezone

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import run_due_snapshot

    now = timezone.now()
    Crawl.objects.filter(pk=snapshot.crawl_id).update(status=Crawl.StatusChoices.STARTED, retry_at=now, modified_at=now)
    Snapshot.objects.filter(pk=snapshot.pk).update(
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=now,
        downloaded_at=None,
        url=blocking_http_server.url,
        config={"PLUGINS": "wget"},
    )
    snapshot.refresh_from_db()
    errors = []

    def run_snapshot():
        try:
            assert run_due_snapshot(snapshot, lock_seconds=60) is True
        except BaseException as err:
            errors.append(err)
        finally:
            blocking_http_server.request_started.set()

    runner = Thread(target=run_snapshot, name="archivebox-test-admin-wget-runner")
    runner.start()
    blocking_http_server.request_started.wait()
    assert errors == []
    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget")
    assert result.status == ArchiveResult.StatusChoices.STARTED
    yield result
    blocking_http_server.release_response.set()
    runner.join()
    assert errors == []


@pytest.fixture
def real_skipped_hash_projection(snapshot, cached_abxpkg_lib_dir):
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=cached_abxpkg_lib_dir,
        env={"HASHES_ENABLED": "False"},
    )


def test_snapshot_changelist_uses_stable_ordering_without_unordered_paginator_warning(admin_client, snapshot):
    url = reverse("admin:core_snapshot_changelist")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert not any(issubclass(warning.category, UnorderedObjectListWarning) for warning in caught)
    assert response.context["cl"].queryset.ordered is True
    assert response.context["cl"].queryset.query.order_by[0] == "-created_at"
    assert b"archivebox-search-stream-status" in response.content
    assert b"Searching matching snapshots..." in response.content


def test_snapshot_changelist_preview_uses_prefetched_output_files(admin_client, snapshot, real_hash_projection):
    from archivebox.core.models import ArchiveResult

    snapshot.title = "Preview destination test"
    snapshot.save(update_fields=["title"])
    _process, result = real_hash_projection
    ArchiveResult.objects.filter(pk=result.pk).update(
        plugin="screenshot",
        hook_name="on_Snapshot__40_screenshot.js",
        output_size=128,
        output_files={"screenshot.png": {"size": 128, "root_relative": True}},
    )

    response = admin_client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert b'class="snapshot-preview' in response.content
    assert b"screenshot.png" in response.content
    html = response.content.decode()
    preview_cell = re.search(r'<td class="field-preview_icon">(.*?)</td>', html, re.S)
    title_cell = re.search(r'<td class="field-title_str">(.*?)</td>', html, re.S)
    assert preview_cell and title_cell
    preview_link = re.search(r'<a href="([^"]+)"', preview_cell.group(1))
    title_link = re.search(r'<a href="([^"]+)"', title_cell.group(1))
    assert preview_link and title_link
    assert preview_link.group(1) == title_link.group(1)
    assert preview_link.group(1).endswith(f"/{snapshot.archive_path_from_db}/index.html")


def test_snapshot_grid_missing_preview_is_inside_snapshot_detail_link(admin_client, snapshot):
    snapshot.status = snapshot.StatusChoices.SEALED
    snapshot.save(update_fields=["status"])

    response = admin_client.get(reverse("admin:grid"), HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    html = response.content.decode()
    thumbnail_link = re.search(
        r'<a href="([^"]+)" class="card-thumbnail">(.*?)</a>',
        html,
        re.S,
    )
    title_link = re.search(
        r'<div class="card-title"[^>]*>\s*<a href="([^"]+)">',
        html,
        re.S,
    )
    assert thumbnail_link and title_link
    assert thumbnail_link.group(1) == title_link.group(1)
    assert thumbnail_link.group(1).endswith("/index.html")
    assert 'aria-label="Preview of example.com"' in thumbnail_link.group(2)
    assert "▤" in thumbnail_link.group(2)


def test_snapshot_grid_serves_extension_preview_from_authenticated_admin_origin(admin_client, snapshot, real_hash_projection):
    _process, result = real_hash_projection
    preview_dir = Path(snapshot.output_dir) / "chrome_extension_screenshot"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_bytes = b"\x89PNG\r\n\x1a\nreal-extension-preview"
    (preview_dir / "screenshot.png").write_bytes(preview_bytes)
    result.plugin = "chrome_extension_screenshot"
    result.status = "succeeded"
    result.output_files = {"screenshot.png": {"size": len(preview_bytes), "mimetype": "image/png"}}
    result.save(update_fields=["plugin", "status", "output_files"])

    grid_response = admin_client.get(reverse("admin:grid"), HTTP_HOST=ADMIN_TEST_HOST)

    assert grid_response.status_code == 200
    html = grid_response.content.decode()
    preview_url = reverse(
        "admin:core_snapshot_preview",
        args=(snapshot.pk, "chrome_extension_screenshot", "screenshot.png"),
    )
    assert f'src="{preview_url}"' in html
    assert "JSON.parse(this.dataset.candidates)" in html
    assert "this.dataset.index=i" in html
    from html import unescape
    import json

    candidates = json.loads(unescape(re.search(r'data-candidates="([^"]+)"', html).group(1)))
    assert [candidate["url"] for candidate in candidates] == [preview_url]

    preview_response = admin_client.get(preview_url, HTTP_HOST=ADMIN_TEST_HOST)

    assert preview_response.status_code == 200
    assert b"".join(preview_response.streaming_content) == preview_bytes
    assert preview_response["Content-Type"] == "image/png"
    assert {part.strip() for part in preview_response["Cache-Control"].split(",")} == {
        "private",
        "max-age=604800",
        "immutable",
    }
    assert {part.strip() for part in preview_response["Vary"].split(",")} >= {"Cookie", "Authorization"}
    assert preview_response["X-Content-Type-Options"] == "nosniff"

    not_modified = admin_client.get(
        preview_url,
        HTTP_HOST=ADMIN_TEST_HOST,
        HTTP_IF_MODIFIED_SINCE=preview_response["Last-Modified"],
    )
    assert not_modified.status_code == 304
    assert {part.strip() for part in not_modified["Cache-Control"].split(",")} == {
        "private",
        "max-age=60",
        "stale-while-revalidate=300",
    }
    assert {part.strip() for part in not_modified["Vary"].split(",")} >= {"Cookie", "Authorization"}

    denied = Client().get(preview_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert denied.status_code in (301, 302)
    assert {part.strip() for part in denied["Cache-Control"].split(",")} == {"private", "no-store"}

    disallowed_dir = Path(snapshot.output_dir) / "singlefile"
    disallowed_dir.mkdir(parents=True, exist_ok=True)
    (disallowed_dir / "singlefile.html").write_text("<script>document.cookie</script>", encoding="utf-8")
    result.plugin = "singlefile"
    result.output_files = {"singlefile.html": {"size": 32, "mimetype": "text/html"}}
    result.save(update_fields=["plugin", "output_files"])
    disallowed_url = reverse("admin:core_snapshot_preview", args=(snapshot.pk, "singlefile", "singlefile.html"))

    assert admin_client.get(disallowed_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_snapshot_result_health_filter_uses_live_status_rows(admin_client, snapshot):
    from archivebox.core.models import ArchiveResult

    for plugin, status in (
        ("title", ArchiveResult.StatusChoices.FAILED),
        ("wget", ArchiveResult.StatusChoices.FAILED),
        ("hashes", ArchiveResult.StatusChoices.SUCCEEDED),
    ):
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            hook_name=f"on_Snapshot__50_{plugin}.py",
            status=status,
        )

    response = admin_client.get(
        reverse("admin:core_snapshot_changelist"),
        {"archiveresult_status": "failed"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    assert snapshot in response.context["cl"].queryset


def test_snapshot_icons_reflect_live_results_without_stale_html_cache(snapshot):
    from archivebox.core.models import ArchiveResult

    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={"hashes.json": {"size": 10}},
    )

    assert "hashes" in str(snapshot.icons())
    ArchiveResult.objects.filter(pk=result.pk).update(status=ArchiveResult.StatusChoices.FAILED)
    assert "hashes" not in str(snapshot.icons())


def test_snapshot_admin_tag_editor_escapes_tag_json_script_breakout(admin_client, snapshot):
    from archivebox.core.models import Tag

    tag = Tag.objects.create(name="safe-tag")
    snapshot.tags.add(tag)
    malicious_name = '</script><script id="archivebox-tag-xss">window.__archivebox_tag_xss__=1</script>'
    Tag.objects.filter(pk=tag.pk).update(name=malicious_name)

    response = admin_client.get(reverse("admin:core_snapshot_change", args=[snapshot.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    body = response.content

    assert response.status_code == 200
    assert malicious_name.encode() not in body
    assert b'<script id="archivebox-tag-xss">' not in body
    assert b'\\u003C/script\\u003E\\u003Cscript id=\\"archivebox-tag-xss\\"\\u003E' in body
    assert b"&lt;/script&gt;&lt;script id=&quot;archivebox-tag-xss&quot;&gt;" in body


def test_snapshot_admin_archive_results_escape_extractor_output(admin_client, snapshot, real_hash_projection):
    from archivebox.core.models import ArchiveResult

    payload = '<img src=x onerror="window.__archivebox_archiveresult_xss__=1">'
    _process, result = real_hash_projection
    ArchiveResult.objects.filter(pk=result.pk).update(output_str=payload)

    response = admin_client.get(reverse("admin:core_snapshot_change", args=[snapshot.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    body = response.content

    assert response.status_code == 200
    assert payload.encode() not in body
    assert b'<img src=x onerror="window.__archivebox_archiveresult_xss__=1">' not in body
    assert b"&lt;img src=x onerror=&quot;window.__archivebox_archiveresult_xss__=1&quot;&gt;" in body


def test_snapshot_admin_archive_result_table_escapes_persisted_string_fields(admin_client, snapshot, real_hash_projection):
    from archivebox.core.models import ArchiveResult

    process, result = real_hash_projection
    machine = process.machine
    type(machine).objects.filter(pk=machine.pk).update(hostname='<script id="machine-xss">x</script>')
    type(process).objects.filter(pk=process.pk).update(pwd='/tmp/archivebox"><script id="pwd-xss">x</script>')
    ArchiveResult.objects.filter(pk=result.pk).update(
        output_files={'evil"><script id="file-xss">x</script>.txt': {"size": 12, "mimetype": "text/plain"}},
        output_str='hashes/evil"><script id="file-xss">x</script>.txt',
        plugin='<script id="plugin-xss">x</script>',
    )

    response = admin_client.get(reverse("admin:core_snapshot_change", args=[snapshot.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    body = response.content

    assert response.status_code == 200
    assert b'<script id="machine-xss">' not in body
    assert b'<script id="pwd-xss">' not in body
    assert b'<script id="file-xss">' not in body
    assert b'<script id="plugin-xss">' not in body
    assert b"&lt;script id=&quot;machine-xss&quot;&gt;" in body
    assert b"&lt;script id=&quot;pwd-xss&quot;&gt;" in body
    assert b"&lt;script id=&quot;file-xss&quot;&gt;" in body
    assert b"&lt;script id=&quot;plugin-xss&quot;&gt;" in body


def test_snapshot_changelist_bulk_permissions_action_updates_selected_snapshots(client, admin_user, crawl, snapshot):
    client.force_login(admin_user)
    url = reverse("admin:core_snapshot_changelist")

    response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert b'value="set_snapshot_permissions"' in response.content
    assert "Permissions ▾".encode() in response.content
    assert b"Set Permissions" not in response.content

    response = client.post(
        url,
        {
            "action": "set_snapshot_permissions",
            "permissions": "private",
            ACTION_CHECKBOX_NAME: [str(snapshot.pk)],
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.config["PERMISSIONS"] == "private"


def test_snapshot_admin_preview_uses_extension_screenshot_when_standard_screenshot_missing(snapshot, real_hash_projection):
    from archivebox.config.common import get_config
    from archivebox.core.admin_site import archivebox_admin
    from archivebox.core.admin_snapshots import SnapshotAdmin
    from archivebox.core.models import ArchiveResult, Snapshot

    _process, result = real_hash_projection
    ArchiveResult.objects.filter(pk=result.pk).update(
        plugin="chrome_extension_screenshot",
        output_files={
            "screenshot-1.png": {"size": 2},
            "screenshot.png": {"size": 1},
        },
    )

    admin = SnapshotAdmin(Snapshot, archivebox_admin)
    request = RequestFactory().get("/", HTTP_HOST="admin.archivebox.localhost:5797")
    request.archivebox_config = get_config()
    admin.request = request

    preview = admin._get_preview_data(snapshot)

    assert preview is not None
    assert "chrome_extension_screenshot/screenshot-1.png" in preview["img_url"]
    assert "chrome_extension_screenshot/screenshot.png" in preview["fallback_list"]
    assert "chrome_extension_screenshot/screenshot-2.png" not in preview["fallback_list"]


def test_snapshot_admin_attributes_new_tags_to_authenticated_user(client, snapshot, admin_user):
    from archivebox.core.models import Tag

    client.force_login(admin_user)
    response = client.post(
        reverse("admin:core_snapshot_change", args=[snapshot.pk]),
        {
            "url": snapshot.url,
            "title": snapshot.title or "",
            "tags_editor": "admin-created-tag",
            "permissions_config": "private",
            "status": snapshot.status,
            "retry_at": "",
            "bookmarked_at_0": snapshot.bookmarked_at.date().isoformat(),
            "bookmarked_at_1": snapshot.bookmarked_at.time().isoformat(),
            "crawl": str(snapshot.crawl_id),
            "config": '{"SAVE_ARCHIVE_DOT_ORG": "false"}',
            "notes": "",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 302, response.context and response.context["adminform"].form.errors
    tag = Tag.objects.get(name="admin-created-tag")
    assert tag.created_by == admin_user
    assert snapshot.tags.filter(pk=tag.pk).exists()


class TestSnapshotProgressStats:
    """Tests for Snapshot.get_progress_stats() method."""

    def test_get_progress_stats_empty(self, snapshot):
        """Test progress stats with no archive results."""
        stats = snapshot.get_progress_stats()

        assert stats["total"] == 0
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0
        assert stats["running"] == 0
        assert stats["pending"] == 0
        assert stats["percent"] == 0
        assert stats["output_size"] == 0
        assert stats["is_sealed"] is False

    def test_get_progress_stats_with_results(
        self,
        snapshot,
        real_hash_projection,
        real_parse_projection,
        real_failed_title_projection,
        running_wget_projection,
    ):
        """Test progress stats with various archive result statuses."""
        from archivebox.core.models import ArchiveResult

        succeeded_results = [real_hash_projection[1], real_parse_projection[1]]
        failed_result = real_failed_title_projection[1]
        started_result = running_wget_projection
        assert all(result.status == ArchiveResult.StatusChoices.SUCCEEDED for result in succeeded_results)
        assert failed_result.status == ArchiveResult.StatusChoices.FAILED
        assert started_result.status == ArchiveResult.StatusChoices.STARTED

        stats = snapshot.get_progress_stats()

        assert stats["total"] == 4
        assert stats["succeeded"] == 2
        assert stats["failed"] == 1
        assert stats["running"] == 1
        assert stats["output_size"] == sum(result.output_size for result in [*succeeded_results, failed_result, started_result])
        assert stats["percent"] == 75  # (2 succeeded + 1 failed) / 4 total

    def test_snapshot_admin_progress_uses_expected_hook_total_not_observed_result_count(
        self,
        snapshot,
        running_wget_projection,
    ):
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.core.admin_snapshots import SnapshotAdmin
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.config.common import get_config
        from django.urls import resolve

        assert running_wget_projection.status == ArchiveResult.StatusChoices.STARTED

        prefetched_snapshot = Snapshot.objects.prefetch_related("archiveresult_set").get(pk=snapshot.pk)
        admin = SnapshotAdmin(Snapshot, archivebox_admin)
        request = RequestFactory().get("/", HTTP_HOST="archivebox.localhost:5797")
        request.resolver_match = resolve("/")
        request.archivebox_config = get_config()
        admin.request = request
        expected_total = admin._get_expected_hook_total(prefetched_snapshot)

        stats = admin._get_progress_stats(prefetched_snapshot)
        html = str(admin.status_with_progress(prefetched_snapshot))

        assert expected_total > 1
        assert stats["total"] == expected_total
        assert stats["succeeded"] == 0
        assert stats["running"] == 1
        assert stats["pending"] == expected_total - 1
        assert stats["percent"] == 0
        assert f"0/{expected_total} hooks" in html

    def test_get_progress_stats_sealed(self, snapshot):
        """Test progress stats for sealed snapshot."""
        from archivebox.core.models import Snapshot

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save()

        stats = snapshot.get_progress_stats()
        assert stats["is_sealed"] is True

    def test_archive_size_uses_materialized_output_size(self, snapshot, real_hash_projection):
        """archive_size should trust the materialized DB size without touching disk."""
        _process, result = real_hash_projection
        snapshot.refresh_from_db(fields=["output_size"])

        assert result.output_size > 0
        assert snapshot.archive_size == result.output_size

    def test_snapshot_serialization_exposes_output_size_alias(self, snapshot, real_hash_projection):
        """Snapshot serializers should expose output_size as an alias of archive_size."""
        _process, result = real_hash_projection
        snapshot.refresh_from_db(fields=["output_size"])

        assert snapshot.to_dict()["archive_size"] == result.output_size
        assert snapshot.to_dict()["output_size"] == result.output_size
        assert snapshot.to_dict()["status"] == snapshot.status
        assert snapshot.to_json()["archive_size"] == result.output_size
        assert snapshot.to_json()["output_size"] == result.output_size
        assert snapshot.to_csv(cols=["output_size"]) == str(result.output_size)
        assert snapshot.to_csv(cols=["status"]) == '"started"'

    def test_is_archived_true_for_sealed_snapshot(self, snapshot):
        """Sealed snapshots should count as archived."""
        from archivebox.core.models import Snapshot

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save(update_fields=["status", "modified_at"])

        assert snapshot.is_archived is True

    def test_discover_outputs_uses_output_file_metadata_size(self, snapshot, real_hash_projection):
        """discover_outputs should use output_files metadata before filesystem fallbacks."""
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "screenshot"
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot_file = output_dir / "screenshot.png"
        shutil.copyfile(REPO_ROOT / "docs" / "_static" / "icon.png", screenshot_file)

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(
            plugin="screenshot",
            output_str="",
            output_files={
                "screenshot.png": {
                    "size": screenshot_file.stat().st_size,
                    "mimetype": "image/png",
                    "extension": "png",
                },
            },
            output_size=0,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)
        screenshot_output = next(output for output in outputs if output["name"] == "screenshot")

        assert screenshot_output["path"] == "screenshot/screenshot.png"
        assert screenshot_output["size"] == screenshot_file.stat().st_size

    def test_media_helpers_use_output_file_metadata_without_disk(self):
        """Template helpers should derive media lists and sizes from output_files metadata."""
        from archivebox.core.templatetags.core_tags import _count_media_files, _list_media_files

        result = SimpleNamespace(
            output_files={
                "video.mp4": {"size": 111, "mimetype": "video/mp4", "extension": "mp4"},
                "audio.mp3": {"size": 222, "mimetype": "audio/mpeg", "extension": "mp3"},
            },
            snapshot_dir="/tmp/does-not-need-to-exist",
            plugin="ytdlp",
        )

        assert _count_media_files(result) == 2
        assert _list_media_files(result) == [
            {
                "name": "video.mp4",
                "path": "ytdlp/video.mp4",
                "size": 111,
                "media_type": "video",
                "is_video": True,
                "is_audio": False,
                "is_browser_playable": True,
            },
            {
                "name": "audio.mp3",
                "path": "ytdlp/audio.mp3",
                "size": 222,
                "media_type": "audio",
                "is_video": False,
                "is_audio": True,
                "is_browser_playable": True,
            },
        ]

    def test_ytdlp_discover_outputs_prefers_browser_playable_video(self, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_files={
                "thumbnail.jpg": {"size": 20_000, "mimetype": "image/jpeg", "extension": "jpg"},
                "large.mkv": {"size": 10_000, "mimetype": "video/x-matroska", "extension": "mkv"},
                "small.mp4": {"size": 111, "mimetype": "video/mp4", "extension": "mp4"},
            },
            output_size=30_111,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)
        ytdlp_output = next(output for output in outputs if output["name"] == "ytdlp")

        assert ytdlp_output["path"] == "ytdlp/small.mp4"

    def test_discover_outputs_falls_back_to_hashes_index_without_filesystem_walk(
        self,
        snapshot,
        real_hash_projection,
        cached_abxpkg_lib_dir,
    ):
        """Snapshots can render cards from the shipped hashes manifest when DB output_files are missing."""
        from archivebox.core.models import ArchiveResult

        _origin_process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(
            plugin="responses",
            output_str="141 responses",
            output_files={},
        )

        responses_dir = Path(snapshot.output_dir) / "responses"
        response_html = responses_dir / "all" / "20260323T073504__GET__example.com__.html"
        response_html.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "README.md", response_html)
        shutil.copyfile(REPO_ROOT / "README.md", responses_dir / "index.jsonl")

        process, _hash_result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=cached_abxpkg_lib_dir,
        )
        assert process.exit_code == 0, process.stderr
        assert (Path(snapshot.output_dir) / "hashes" / "hashes.json").is_file()

        outputs = snapshot.discover_outputs(include_filesystem_fallback=True)

        assert next(output for output in outputs if output["name"] == "responses")["path"] == (
            "responses/all/20260323T073504__GET__example.com__.html"
        )

    def test_discover_outputs_falls_back_to_filesystem_for_missing_db_and_hashes(self, snapshot):
        """Snapshot page can still recover cards from plugin dirs when DB metadata is missing."""
        responses_dir = Path(snapshot.output_dir) / "responses"
        (responses_dir / "all").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "README.md", responses_dir / "index.jsonl")
        shutil.copyfile(REPO_ROOT / "README.md", responses_dir / "all" / "20260323T073504__GET__example.com__.html")

        outputs = snapshot.discover_outputs(include_filesystem_fallback=True)

        assert next(output for output in outputs if output["name"] == "responses")["path"] == (
            "responses/all/20260323T073504__GET__example.com__.html"
        )

    def test_embed_path_db_ignores_human_readable_output_messages(self, snapshot, real_failed_title_projection):
        _process, result = real_failed_title_projection

        assert result.embed_path_db() is None

    @pytest.mark.parametrize(
        "output_str",
        [
            ("wget/example.com/index.html"),
            (""),
        ],
    )
    def test_embed_path_db_selects_html_output(self, snapshot, real_hash_projection, output_str):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "wget" / "example.com" / "assets" / "css"
        output_dir.mkdir(parents=True, exist_ok=True)
        (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "README.md", Path(snapshot.output_dir) / "wget" / "example.com" / "index.html")
        shutil.copyfile(REPO_ROOT / "archivebox" / "templates" / "static" / "bootstrap.min.css", output_dir / "mobile.css")

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(
            plugin="wget",
            output_str=output_str,
            output_files={
                "example.com/assets/css/mobile.css": {"size": (output_dir / "mobile.css").stat().st_size, "mimetype": "text/css"},
                "example.com/index.html": {
                    "size": (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").stat().st_size,
                    "mimetype": "text/html",
                },
            },
        )
        result.refresh_from_db()

        assert result.embed_path_db() == "wget/example.com/index.html"

    def test_embed_path_db_rejects_mimetype_like_output_str(self, snapshot, real_hash_projection):
        from archivebox.core.models import ArchiveResult

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(plugin="staticfile", output_str="text/html", output_files={})
        result.refresh_from_db()

        assert result.embed_path_db() is None

    def test_embed_path_db_rejects_output_str_that_does_not_exist_on_disk(self, snapshot, real_hash_projection):
        from archivebox.core.models import ArchiveResult

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(plugin="dns", output_str="1.2.3.4", output_files={})
        result.refresh_from_db()

        assert result.embed_path_db() is None

    def test_embed_path_db_uses_output_file_fallbacks_without_disk_check(self, snapshot, real_hash_projection):
        from archivebox.core.models import ArchiveResult

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(
            plugin="responses",
            output_str="",
            output_files={
                "all/20260323T073504__GET__example.com__.html": {"size": 789, "mimetype": "text/html"},
            },
        )
        result.refresh_from_db()

        assert result.embed_path_db() == "responses/all/20260323T073504__GET__example.com__.html"

    def test_discover_outputs_keeps_jsonl_only_plugins_with_non_path_output_str(
        self,
        snapshot,
        real_hash_projection,
        real_noresults_projection,
    ):
        from archivebox.core.models import ArchiveResult

        _hash_process, dns_result = real_hash_projection
        _parse_process, ssl_result = real_noresults_projection
        ArchiveResult.objects.filter(pk=dns_result.pk).update(
            plugin="dns",
            output_str="1.2.3.4",
            output_files={"dns.jsonl": {"size": 1519, "mimetype": "application/jsonl"}},
        )
        ArchiveResult.objects.filter(pk=ssl_result.pk).update(
            plugin="sslcerts",
            output_str="WR2",
            output_files={"sslcerts.jsonl": {"size": 3138, "mimetype": "application/jsonl"}},
        )

        outputs = {output["name"]: output for output in snapshot.discover_outputs(include_filesystem_fallback=False)}

        assert outputs["dns"]["path"] == "dns/dns.jsonl"
        assert outputs["sslcerts"]["path"] == "sslcerts/sslcerts.jsonl"
        assert outputs["dns"]["is_metadata"] is True
        assert outputs["sslcerts"]["is_metadata"] is True

    def test_embed_path_uses_explicit_fallback_not_first_output_file(self, snapshot, real_hash_projection):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "responses" / "all"
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "README.md", output_dir / "20260323T073504__GET__example.com__.html")

        _process, result = real_hash_projection
        ArchiveResult.objects.filter(pk=result.pk).update(
            plugin="responses",
            output_str="141 responses",
            output_files={
                "all/20260323T073504__GET__example.com__app.js": {"size": 123, "mimetype": "application/javascript"},
                "all/20260323T073504__GET__example.com__.html": {"size": 789, "mimetype": "text/html"},
                "index.jsonl": {"size": 456, "mimetype": "application/jsonl"},
            },
        )
        result.refresh_from_db()

        assert result.embed_path_db() == "responses/all/20260323T073504__GET__example.com__.html"
        assert result.embed_path() == "responses/all/20260323T073504__GET__example.com__.html"

    def test_detail_page_auxiliary_items_include_failed_plugins(self, snapshot, real_failed_title_projection):
        _process, result = real_failed_title_projection

        loose_items, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[])

        assert loose_items == []
        assert failed_items == [
            {
                "name": f"{result.plugin} (failed)",
                "path": result.plugin,
                "is_dir": True,
                "size": result.output_size,
            },
        ]

    def test_detail_page_auxiliary_items_include_hidden_failed_plugins(self, snapshot, real_failed_title_projection):
        _process, result = real_failed_title_projection

        _, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[], hidden_card_plugins={result.plugin})

        assert failed_items == [
            {
                "name": f"{result.plugin} (failed)",
                "path": result.plugin,
                "is_dir": True,
                "size": result.output_size,
            },
        ]

    def test_detail_page_auxiliary_items_exclude_noresults_and_skipped(
        self,
        snapshot,
        real_noresults_projection,
        real_skipped_hash_projection,
    ):
        from archivebox.core.models import ArchiveResult

        assert real_noresults_projection[1].status == ArchiveResult.StatusChoices.NORESULTS
        assert real_skipped_hash_projection[1].status == ArchiveResult.StatusChoices.SKIPPED

        _, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[])

        assert failed_items == []

    def test_plugin_full_renders_db_embed_path(self, snapshot, real_hash_projection):
        from archivebox.core.templatetags import core_tags

        _process, result = real_hash_projection
        embed_path = result.embed_path_db()
        assert embed_path is not None

        html = str(core_tags.plugin_full({"request": None}, result))

        assert embed_path in html
        # The viewer fetches raw data; its View raw action may use preview=1.
        output_url = re.search(r"const output\s*=\s*new URL\('([^']+)'", html)
        assert output_url is not None
        assert output_url.group(1).endswith(embed_path)
        assert "?" not in output_url.group(1)
        assert html != "http://snap-ffa4215f6d64.archivebox.localhost:5797"

    def test_plugin_full_returns_empty_for_none_result(self):
        from archivebox.core.templatetags import core_tags

        assert core_tags.plugin_full({"request": None}, None) == ""

    def test_write_html_details_succeeds_with_index_only_fallback_output(self, snapshot):
        output_dir = Path(snapshot.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "README.md", output_dir / "index.jsonl")

        snapshot.write_html_details()

        rendered = (output_dir / "index.html").read_text(encoding="utf-8")

        assert "full-page-iframe" in rendered
        assert "index.jsonl?preview=1" in rendered
        assert "height: calc(100vh - 210px)" not in rendered
        assert "iframe-large" not in rendered
        assert "fitPreviewFrameToContent" in rendered
        assert "wrapper.style.height = `${contentHeight}px`" in rendered
        assert 'class="header-toggle header-toggle-trigger"' not in rendered
        assert "event.preventDefault()" in rendered
        assert rendered.count("addEventListener('click', handleSnapshotHeaderToggle)") == 1

    def test_static_snapshot_detail_uses_same_output_cards_with_relative_files(self, snapshot):
        from archivebox.config import CONSTANTS
        from archivebox.core.models import ArchiveResult
        from archivebox.core.views import SnapshotView

        output_dir = Path(snapshot.output_dir)
        singlefile_dir = output_dir / "singlefile"
        singlefile_dir.mkdir(parents=True, exist_ok=True)
        output_file = singlefile_dir / "singlefile.html"
        output_file.write_text("<html><body>real static output</body></html>", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="singlefile.html",
            output_files={"singlefile.html": {"size": output_file.stat().st_size}},
            output_size=output_file.stat().st_size,
        )
        favicon_dir = output_dir / "favicon"
        favicon_dir.mkdir(parents=True, exist_ok=True)
        favicon_file = favicon_dir / "favicon.ico"
        favicon_file.write_bytes(b"real favicon")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="favicon",
            hook_name="on_Snapshot__50_favicon.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="favicon.ico",
            output_files={"favicon.ico": {"size": favicon_file.stat().st_size}},
            output_size=favicon_file.stat().st_size,
        )

        request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
        request.user = AnonymousUser()
        live_html = SnapshotView.render_live_index(request, snapshot).content.decode()

        snapshot.write_html_details()
        snapshot.write_json_details()
        static_html = (output_dir / "index.html").read_text(encoding="utf-8")
        static_json = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))

        assert re.findall(r'data-plugin-name="([^"]+)"', static_html) == re.findall(r'data-plugin-name="([^"]+)"', live_html)
        assert 'data-plugin-name="singlefile"' in static_html
        assert 'href="./singlefile/singlefile.html"' in static_html
        assert 'data-default-src="./singlefile/singlefile.html"' in static_html
        assert 'src="./favicon/favicon.ico"' in static_html
        root_href = os.path.relpath(CONSTANTS.DATA_DIR, start=output_dir).replace(os.sep, "/")
        assert f'href="{root_href}/index.html" class="header-archivebox"' in static_html
        assert f"/snapshot/{snapshot.id.hex}" not in static_html
        assert "/static/jquery.min.js" not in static_html
        assert static_json["archive_path"].startswith("archive/users/")
        assert static_json["archive_url"] == f"./{static_json['archive_path']}/index.html"

    def test_output_cards_use_consistent_preview_grid_rows(self):
        template = (REPO_ROOT / "archivebox" / "templates" / "core" / "snapshot.html").read_text()
        thumb_grid_css = template.split(".thumb-grid {", 1)[1].split("}", 1)[0]
        thumb_card_css = template.split(".thumb-card {", 1)[1].split("}", 1)[0]
        auxiliary_card_css = template.split(".thumb-card:not([data-plugin-name]) {", 1)[1].split("}", 1)[0]

        assert "display: grid;" in thumb_grid_css
        assert "grid-template-columns: repeat(auto-fit, minmax(clamp(180px, 14vw, 250px), 1fr));" in thumb_grid_css
        assert "grid-auto-flow: row dense;" in thumb_grid_css
        assert "grid-auto-rows: 42px;" in thumb_grid_css
        assert "grid-row: span 3;" in thumb_card_css
        assert "order: 1;" in auxiliary_card_css
        assert ".thumb-card:has([data-compact])" not in template


class TestSnapshotOutputDeletion:
    @staticmethod
    def _create_output(snapshot, *, plugin="screenshot", hook_name="on_Snapshot__50_screenshot.py", size=11):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / plugin
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output.png"
        output_path.write_bytes(b"x" * size)
        return ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            hook_name=hook_name,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="output.png",
            output_files={"output.png": {"size": size, "mimetype": "image/png"}},
            output_size=size,
        )

    def test_snapshot_detail_only_shows_delete_controls_to_superusers(self, snapshot, admin_user):
        from archivebox.core.views import SnapshotView

        result = self._create_output(snapshot)
        request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
        request.user = admin_user

        html = SnapshotView.render_live_index(request, snapshot).content.decode()

        assert f'data-archive-result-ids="{result.id}"' in html
        assert 'title="Delete this output"' in html
        assert 'data-delete-handoff="1"' in html
        assert "const queuedOutputIds = new Set()" in html
        assert "window.location.assign(deleteUrl)" in html
        assert "/admin/core/archiveresult/" in html
        assert "[deleting]" in html
        assert ">×</button>" in html
        assert "delete-output-csrf" not in html
        assert "[data-archive-result-ids]:hover" in html
        assert "[data-archive-result-ids].delete-pending" in html
        assert "button.classList.toggle('delete-pending', queued)" in html

        request.user = AnonymousUser()
        anonymous_html = SnapshotView.render_live_index(request, snapshot).content.decode()
        assert "data-archive-result-ids" not in anonymous_html
        assert 'title="Delete this output"' not in anonymous_html

        request.COOKIES[ADMIN_LOGIN_HINT_COOKIE] = "1"
        hinted_html = SnapshotView.render_live_index(request, snapshot).content.decode()
        assert f'data-archive-result-ids="{result.id}"' in hinted_html
        assert "delete-output-csrf" not in hinted_html

    def test_snapshot_delete_handoff_requires_superuser_confirmation_then_uses_standard_admin_action(self, client, snapshot, admin_user):
        from archivebox.core.models import ArchiveResult

        result = self._create_output(snapshot)
        delete_url = reverse("admin:core_archiveresult_changelist")
        handoff_query = {
            "action": "delete_selected",
            ACTION_CHECKBOX_NAME: str(result.id),
            "snapshot": str(snapshot.id),
        }

        logged_out = client.get(delete_url, handoff_query, HTTP_HOST=ADMIN_TEST_HOST)
        assert logged_out.status_code == 302
        assert ArchiveResult.objects.filter(pk=result.pk).exists()

        staff_user = admin_user.__class__.objects.create_user(username="output-reviewer", password="testpassword", is_staff=True)
        client.force_login(staff_user)
        denied = client.get(delete_url, handoff_query, HTTP_HOST=ADMIN_TEST_HOST)
        assert denied.status_code == 403
        assert ArchiveResult.objects.filter(pk=result.pk).exists()

        client.force_login(admin_user)
        confirmation = client.get(delete_url, handoff_query, HTTP_HOST=ADMIN_TEST_HOST)
        confirmation_html = confirmation.content.decode()
        assert confirmation.status_code == 200
        assert "Yes, I’m sure" in confirmation_html
        assert f'name="{ACTION_CHECKBOX_NAME}" value="{result.id}"' in confirmation_html
        assert confirmation["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in confirmation["Content-Security-Policy"]
        assert ArchiveResult.objects.filter(pk=result.pk).exists()

        confirmed = client.post(
            f"{delete_url}?action=delete_selected&{ACTION_CHECKBOX_NAME}={result.id}&snapshot={snapshot.id}",
            {
                "action": "delete_selected",
                "post": "yes",
                ACTION_CHECKBOX_NAME: str(result.id),
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert confirmed.status_code == 302
        assert not ArchiveResult.objects.filter(pk=result.pk).exists()
        assert str(snapshot.id).replace("-", "")[-12:] in confirmed["Location"]

    def test_batch_delete_removes_plugin_rows_files_and_refreshes_snapshot_size(self, client, snapshot, admin_user):
        from archivebox.core.models import ArchiveResult

        first = self._create_output(snapshot, size=11)
        second = self._create_output(snapshot, hook_name="on_Snapshot__51_screenshot_retry.py", size=13)
        kept = self._create_output(snapshot, plugin="pdf", hook_name="on_Snapshot__60_pdf.py", size=7)
        deleted_dir = Path(first.output_dir)
        kept_dir = Path(kept.output_dir)
        hashes_dir = Path(snapshot.output_dir) / "hashes"
        hashes_dir.mkdir(parents=True, exist_ok=True)
        (hashes_dir / "hashes.json").write_text(
            json.dumps({"files": [{"path": "screenshot/output.png", "size": 13}]}),
        )

        delete_url = reverse("admin:core_archiveresult_changelist")
        delete_data = {
            "action": "delete_selected",
            "post": "yes",
            ACTION_CHECKBOX_NAME: [str(first.id), str(second.id)],
        }
        denied = client.post(
            delete_url,
            delete_data,
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert denied.status_code == 302
        assert deleted_dir.exists()

        client.force_login(admin_user)
        response = client.post(
            delete_url,
            delete_data,
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert response.status_code == 302
        assert not ArchiveResult.objects.filter(pk__in=[first.pk, second.pk]).exists()
        assert ArchiveResult.objects.filter(pk=kept.pk).exists()
        assert not deleted_dir.exists()
        assert kept_dir.exists()
        snapshot.refresh_from_db()
        assert snapshot.output_size == 7
        assert "screenshot" not in {output["name"] for output in snapshot.discover_outputs()}
        assert '"plugin": "screenshot"' not in (Path(snapshot.output_dir) / "index.jsonl").read_text()

    def test_admin_inline_shows_sortable_output_sizes_and_delete_controls(self, client, snapshot, admin_user):
        first = self._create_output(snapshot, plugin="screenshot", size=11)
        second = self._create_output(snapshot, plugin="pdf", hook_name="on_Snapshot__60_pdf.py", size=2048)
        assert client.login(username=admin_user.username, password="testpassword")

        response = client.get(
            reverse("admin:core_snapshot_change", args=[snapshot.pk]),
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        html = response.content.decode()

        assert response.status_code == 200
        assert "data-output-size-sort" in html
        assert 'data-output-size="11"' in html
        assert 'data-output-size="2048"' in html
        assert "11.0 Bytes" in html
        assert "2.0 KB" in html
        assert f'data-archive-result-ids="{first.id}"' in html
        assert f'data-archive-result-ids="{second.id}"' in html
        assert html.count('title="Delete this output"') == 2
        assert reverse("admin:core_archiveresult_changelist") in html
        assert "const queuedOutputIds = new Set()" in html
        assert "action: 'delete_selected'" in html
        assert ">×</button>" in html
        assert "button.classList.toggle('delete-pending', queued)" in html


class TestAdminSnapshotListView:
    """Tests for the admin snapshot list view."""

    def test_list_view_renders(self, client, admin_user):
        """Test that the list view renders successfully."""
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200

    def test_list_view_with_snapshots(self, client, admin_user, snapshot):
        """Test list view with snapshots displays them."""
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_list_view_renders_titleless_snapshot(self, client, admin_user, snapshot):
        """Title-less snapshots should render their URL."""
        from archivebox.core.models import Snapshot

        Snapshot.objects.filter(pk=snapshot.pk).update(title="")

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_list_view_renders_snapshot_replay_link(self, client, admin_user, snapshot):
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content
        assert str(snapshot.pk).encode() in response.content

    def test_list_view_renders_archive_result_plugin(self, client, admin_user, snapshot, real_hash_projection):
        _process, result = real_hash_projection

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert result.plugin.encode() in response.content

    def test_list_view_uses_complete_bulk_progress_stats_without_per_snapshot_queries(self, client, admin_user, snapshot, crawl):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from archivebox.core.models import ArchiveResult, Snapshot

        snapshot.status = Snapshot.StatusChoices.STARTED
        snapshot.save(update_fields=["status", "modified_at"])
        for plugin, status, output_size in (
            ("screenshot", ArchiveResult.StatusChoices.SUCCEEDED, 1024),
            ("title", ArchiveResult.StatusChoices.FAILED, 0),
            ("wget", ArchiveResult.StatusChoices.STARTED, 0),
            ("hashes", ArchiveResult.StatusChoices.SKIPPED, 0),
        ):
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin=plugin,
                hook_name=f"on_Snapshot__50_{plugin}.py",
                status=status,
                output_size=output_size,
                output_files={"screenshot.png": {"size": output_size}} if output_size else {},
            )

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        with CaptureQueriesContext(connection) as single_snapshot_queries:
            response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        rendered_snapshot = next(obj for obj in response.context["cl"].result_list if obj.pk == snapshot.pk)
        assert rendered_snapshot.__dict__["_admin_progress_stats"] == {
            "total": 4,
            "succeeded": 1,
            "failed": 1,
            "running": 1,
            "pending": 0,
            "skipped": 1,
            "noresults": 0,
            "percent": 75,
            "output_size": rendered_snapshot.output_size,
            "is_sealed": False,
        }
        assert "_admin_archiveresults" not in rendered_snapshot.__dict__
        assert [result.plugin for result in rendered_snapshot.__dict__["_admin_output_results"]] == ["screenshot"]

        additional_snapshots = [
            Snapshot.objects.create(
                url=f"https://progress-{index}.example.com",
                crawl=crawl,
                status=Snapshot.StatusChoices.STARTED,
                title=f"Progress {index}",
            )
            for index in range(5)
        ]
        ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(
                    snapshot=additional_snapshot,
                    plugin="wget",
                    hook_name="on_Snapshot__50_wget.py",
                    status=ArchiveResult.StatusChoices.STARTED,
                )
                for additional_snapshot in additional_snapshots
            ],
        )
        with CaptureQueriesContext(connection) as many_snapshot_queries:
            many_response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert many_response.status_code == 200
        single_result_queries = [query for query in single_snapshot_queries.captured_queries if 'FROM "core_archiveresult"' in query["sql"]]
        many_result_queries = [query for query in many_snapshot_queries.captured_queries if 'FROM "core_archiveresult"' in query["sql"]]
        # Status totals, successful outputs, and preview candidates each load in bulk.
        assert len(single_result_queries) == len(many_result_queries) == 3

    def test_list_view_uses_prefetched_tags_without_row_queries(self, client, admin_user, crawl, db):
        """Changelist tag rendering should reuse the prefetched tag cache."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from archivebox.core.models import Snapshot, Tag

        tags = [Tag.objects.create(name=f"perf-tag-{idx}") for idx in range(3)]
        for idx in range(5):
            snap = Snapshot.objects.create(
                url=f"https://example.com/{idx}",
                crawl=crawl,
                status=Snapshot.StatusChoices.STARTED,
                title=f"Title {idx}",
            )
            snap.tags.add(*tags[: (idx % 3) + 1])

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        per_row_tag_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if 'FROM "core_tag"' in query["sql"] and '"core_snapshot_tags"."snapshot_id"' in query["sql"] and " IN " not in query["sql"]
        ]
        assert per_row_tag_queries == []

    def test_grid_view_renders(self, client, admin_user, snapshot):
        """Test that the grid view renders successfully."""
        client.force_login(admin_user)
        url = reverse("admin:grid")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b'<section class="cards">' in response.content
        assert snapshot.url.encode() in response.content

    def test_grid_card_component_order(self, client, admin_user, snapshot, real_hash_projection):
        """Snapshot cards should keep metadata, title, URL, preview, and outputs in scan order."""
        from archivebox.core.models import Tag

        _process, result = real_hash_projection
        assert result.output_size > 0

        snapshot.title = "Example Snapshot"
        snapshot.status = snapshot.StatusChoices.SEALED
        snapshot.save(update_fields=["title", "status", "modified_at"])
        snapshot.tags.add(Tag.objects.create(name="research"))

        client.force_login(admin_user)
        response = client.get(reverse("admin:grid"), HTTP_HOST=ADMIN_TEST_HOST)
        body = response.content.decode()

        assert response.status_code == 200
        assert "🗄" not in body
        assert body.index('name="_selected_action"') < body.index('class="timestamp"')
        assert body.index('class="timestamp"') < body.index('class="card-size"')
        assert body.index('class="card-size"') < body.index('class="link-favicon"')
        assert body.index('class="title-text"') < body.index('class="card-url"')
        assert body.index('class="card-url"') < body.index('class="card-media"')
        assert body.index('class="card-tags"') < body.index('class="card-outputs"')

    def test_view_mode_switcher_present(self, client, admin_user):
        """Test that view mode switcher is present."""
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        # Check for visible snapshot actions-bar controls
        assert b"snapshot-view-toggle" in response.content
        assert b"Grid" in response.content
        assert reverse("admin:grid").encode() in response.content

    def test_change_view_renders_real_redo_failed_action(self, client, admin_user, snapshot):
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert f"/admin/core/snapshot/{snapshot.pk}/redo-failed/".encode() in response.content

    def test_change_view_reuses_resolved_snapshot_for_progress_context(self, client, admin_user, snapshot):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        snapshot.status = snapshot.StatusChoices.STARTED
        snapshot.__class__.objects.filter(pk=snapshot.pk).update(status=snapshot.status)
        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])

        with CaptureQueriesContext(connection) as captured_queries:
            response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        snapshot_reads = [
            query["sql"]
            for query in captured_queries
            if 'FROM "core_snapshot"' in query["sql"] and '"core_snapshot"."id" =' in query["sql"]
        ]
        assert response.status_code == 200
        assert response.context["progress_auto_expand"] is True
        assert response.context["progress_endpoint"].endswith(f"?snapshot_id={snapshot.pk}")
        assert len(snapshot_reads) == 1

    def test_snapshot_view_url_uses_canonical_replay_url_for_mode(self, snapshot):
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.core.admin_snapshots import SnapshotAdmin
        from archivebox.config.common import get_config

        admin = SnapshotAdmin(snapshot.__class__, archivebox_admin)

        request = RequestFactory().get("/", HTTP_HOST="admin.archivebox.localhost:5797")
        request.archivebox_config = get_config(overrides={"SERVER_SECURITY_MODE": "safe-subdomains-fullreplay"})
        admin.request = request
        assert admin.get_snapshot_view_url(snapshot) == f"http://snap-{str(snapshot.pk).replace('-', '')[-12:]}.archivebox.localhost:5797"

        request.archivebox_config = get_config(overrides={"SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay"})
        assert admin.get_snapshot_view_url(snapshot) == f"http://archivebox.localhost:5797/snapshot/{snapshot.pk}"

    def test_find_snapshots_for_url_matches_fragment_suffixed_variants(self, crawl, db):
        from archivebox.core.models import Snapshot
        from archivebox.core.views import SnapshotView

        canonical = Snapshot.objects.create(
            url="https://example.com/page",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
        )
        old_variant = Snapshot.objects.create(
            url="https://example.com/page#2026-03-23T12:34:56",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
        )

        matches = list(SnapshotView.find_snapshots_for_url(canonical.url).order_by("url"))

        assert [snap.url for snap in matches] == [canonical.url, old_variant.url]

    def test_change_view_renders_readonly_tag_pills_near_title(self, client, admin_user, snapshot):
        from archivebox.core.models import Tag

        tag = Tag.objects.create(name="Alpha Research")
        snapshot.tags.add(tag)

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Alpha Research" in response.content
        assert b"tag-editor-inline readonly" in response.content
        assert b'data-readonly="1"' in response.content

    def test_redo_failed_action_requeues_snapshot(self, client, admin_user, snapshot, real_failed_title_projection):
        from archivebox.core.models import ArchiveResult

        _process, failed = real_failed_title_projection

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_redo_failed", args=[snapshot.pk])
        response = client.post(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 302
        assert response["Location"].endswith(f"/admin/core/snapshot/{snapshot.pk}/change/")
        failed.refresh_from_db()
        snapshot.refresh_from_db()
        assert failed.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.status == snapshot.StatusChoices.QUEUED
        assert snapshot.config["RETRY_PLUGINS"] == ["title"]

    def test_list_redo_failed_action_requeues_failed_archiveresults_only(
        self,
        client,
        admin_user,
        snapshot,
        real_failed_title_projection,
        cached_abxpkg_lib_dir,
    ):
        from archivebox.core.models import ArchiveResult

        _failed_process, failed = real_failed_title_projection
        snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        (snapshot.output_dir / "source.txt").write_text("real successful retry peer", encoding="utf-8")
        _success_process, succeeded = _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=cached_abxpkg_lib_dir,
        )
        succeeded_output = succeeded.output_str

        client.force_login(admin_user)
        response = client.post(
            reverse("admin:core_snapshot_changelist"),
            {
                "action": "update_snapshots",
                "_selected_action": [str(snapshot.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert response.status_code == 302
        failed.refresh_from_db()
        succeeded.refresh_from_db()
        snapshot.refresh_from_db()
        assert failed.status == ArchiveResult.StatusChoices.FAILED
        assert failed.output_str
        assert succeeded.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert succeeded.output_str == succeeded_output
        assert snapshot.status == snapshot.StatusChoices.QUEUED
        assert snapshot.config["RETRY_PLUGINS"] == ["title"]

    def test_archive_now_action_uses_original_snapshot_url_without_timestamp_suffix(self, client, admin_user, snapshot):
        from archivebox.crawls.models import Crawl

        existing_crawl_ids = set(Crawl.objects.values_list("id", flat=True))
        snapshot.url = "https://example.com/path#section-1"
        snapshot.save(update_fields=["url"])

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.post(
            url,
            {
                "action": "resnapshot_snapshot",
                "_selected_action": [str(snapshot.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert response.status_code == 302
        new_crawl = Crawl.objects.exclude(id__in=existing_crawl_ids).get()
        assert new_crawl.status == Crawl.StatusChoices.QUEUED
        assert new_crawl.retry_at is not None
        assert new_crawl.urls.strip() == "https://example.com/path#section-1"

    def test_archive_now_action_groups_multiple_snapshots_into_one_crawl(self, client, admin_user, snapshot):
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        existing_crawl_ids = set(Crawl.objects.values_list("id", flat=True))
        other_snapshot = Snapshot.objects.create(
            url="https://example.com/other#frag",
            crawl=snapshot.crawl,
            status=Snapshot.StatusChoices.STARTED,
        )

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.post(
            url,
            {
                "action": "resnapshot_snapshot",
                "_selected_action": [str(snapshot.pk), str(other_snapshot.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )

        assert response.status_code == 302
        new_crawl = Crawl.objects.exclude(id__in=existing_crawl_ids).get()
        assert new_crawl.status == Crawl.StatusChoices.QUEUED
        assert set(new_crawl.urls.splitlines()) == {"https://example.com", "https://example.com/other#frag"}

    def test_change_view_archiveresults_inline_shows_process_and_machine_links(
        self,
        client,
        admin_user,
        snapshot,
        real_hash_projection,
    ):
        process, result = real_hash_projection
        machine = process.machine
        assert result.process_id == process.id

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Process" in response.content
        assert b"Machine" in response.content
        assert str(process.pid).encode() in response.content
        assert machine.hostname.encode() in response.content
        assert reverse("admin:machine_process_change", args=[process.id]).encode() in response.content
        assert reverse("admin:machine_machine_change", args=[machine.id]).encode() in response.content


def test_metadata_card_uses_dedicated_template_and_static_export_keeps_text(real_hash_projection):
    from django.template import Context

    from archivebox.core.templatetags.core_tags import plugin_card

    _process, result = real_hash_projection
    assert result.status == "succeeded"
    live = plugin_card(Context({}), result)
    assert "<iframe " in live
    assert 'preview=1"' in live
    assert "data-compact" not in live
    assert "card=1" not in live
    assert "thumbnail-text-pre" not in live

    exported = plugin_card(Context({"STATIC_EXPORT": True, "STATIC_EXPORT_DIR": result.snapshot.output_dir}), result)
    assert "thumbnail-text-pre" in exported
    assert "&amp;card=1" not in exported


def test_metadata_raw_preview_bypasses_full_template(real_hash_projection, client):
    from archivebox.core.routes_util import get_snapshot_host

    _process, result = real_hash_projection
    snapshot = result.snapshot
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    path = f"/{result.embed_path()}"
    host = get_snapshot_host(str(snapshot.id))
    raw_file = snapshot.output_dir / result.embed_path()

    full = client.get(path + "?preview=1", HTTP_HOST=host)
    assert full.status_code == 200
    assert b'aria-label="Output actions"' in full.content

    raw = client.get(path + "?preview=1&raw=1", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"archivebox-text-preview" in raw.content
    assert b'aria-label="Output actions"' not in raw.content
    assert json.loads(raw_file.read_text())["root_hash"].encode() in raw.content

    download = client.get(path, HTTP_HOST=host)
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == raw_file.read_bytes()


def test_snapshot_grid_and_list_use_responses_image_fallback(client, admin_user, snapshot):
    from archivebox.core.models import ArchiveResult

    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        status=ArchiveResult.StatusChoices.FAILED,
        output_files={"all/largest.png": {"size": 500, "mimetype": "image/png"}},
    )
    client.force_login(admin_user)
    for route in ("admin:grid", "admin:core_snapshot_changelist"):
        response = client.get(reverse(route), HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b"responses/all/largest.png" in response.content


def test_central_preview_ranking_and_malformed_metadata(snapshot):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.preview_util import snapshot_preview_candidates, render_snapshot_preview

    for plugin, files in (
        ("screenshot", {"screenshot.png": {"size": 1}}),
        ("seo", {"featured-image.jpg": {"size": 40}}),
        (
            "responses",
            {
                "all/tracker.png": {"size": 9999, "mimetype": "image/png", "width": 1, "height": 1},
                "all/banner.png": {"size": 500, "mimetype": "image/png", "width": 5000, "height": 20},
                "all/photo.png": {"size": 300, "mimetype": "image/png", "width": 1000, "height": 600},
                "all/legacy.png": {"size": 700, "mimetype": "image/png"},
                "all/broken.png": {"size": "invalid"},
                "all/no-info.png": None,
            },
        ),
        ("favicon", {"favicon.ico": {"size": 10}}),
    ):
        ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="failed", output_files=files)
    candidates = snapshot_preview_candidates(snapshot)
    assert [item["path"] for item in candidates] == [
        "screenshot/screenshot.png",
        "seo/featured-image.jpg",
        "responses/all/photo.png",
        "responses/all/legacy.png",
        "responses/all/banner.png",
        "favicon/favicon.ico",
    ]
    html = render_snapshot_preview(snapshot, lambda candidate: "/" + candidate["path"])
    assert "snapshot-thumbnail" in html
    assert "data-candidates=" in html
    assert "this.remove()" in html
    assert "▤" in html


def test_archivewebpage_recording_metadata_is_text_not_replay(client, snapshot):
    from archivebox.core.routes_util import get_snapshot_host

    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    recording = snapshot.output_dir / "archivewebpage" / "recording.json"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_text('{"collectionId": "recording-metadata"}')

    response = client.get(
        "/archivewebpage/recording.json?preview=1",
        HTTP_HOST=get_snapshot_host(str(snapshot.id)),
    )
    assert response.status_code == 200
    assert b"archivebox-text-preview" in response.content
    assert b"recording-metadata" in response.content
    assert b"navigator.serviceWorker.register" not in response.content
