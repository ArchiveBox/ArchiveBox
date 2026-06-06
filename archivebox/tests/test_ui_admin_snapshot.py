"""Snapshot model and admin UI tests."""

import json
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.paginator import UnorderedObjectListWarning
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_snapshot_changelist_uses_stable_ordering_without_unordered_paginator_warning(admin_client, snapshot):
    url = reverse("admin:core_snapshot_changelist")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert not any(issubclass(warning.category, UnorderedObjectListWarning) for warning in caught)
    assert response.context["cl"].queryset.ordered is True
    assert response.context["cl"].queryset.query.order_by[0] == "-created_at"


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

    def test_get_progress_stats_with_results(self, snapshot, db):
        """Test progress stats with various archive result statuses."""
        from archivebox.core.models import ArchiveResult

        # Create some archive results
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status="succeeded",
            output_size=1000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            status="succeeded",
            output_size=2000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="pdf",
            status="failed",
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="readability",
            status="started",
        )

        stats = snapshot.get_progress_stats()

        assert stats["total"] == 4
        assert stats["succeeded"] == 2
        assert stats["failed"] == 1
        assert stats["running"] == 1
        assert stats["output_size"] == 3000
        assert stats["percent"] == 75  # (2 succeeded + 1 failed) / 4 total

    def test_snapshot_admin_progress_uses_expected_hook_total_not_observed_result_count(self, snapshot, monkeypatch):
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.core.admin_snapshots import SnapshotAdmin
        from archivebox.core.models import ArchiveResult, Snapshot

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__50_wget.py",
            status="succeeded",
            output_size=1000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__54_title.py",
            status="started",
        )

        prefetched_snapshot = Snapshot.objects.prefetch_related("archiveresult_set").get(pk=snapshot.pk)
        admin = SnapshotAdmin(Snapshot, archivebox_admin)
        monkeypatch.setattr(admin, "_get_expected_hook_total", lambda obj: 5)

        stats = admin._get_progress_stats(prefetched_snapshot)
        html = str(admin.status_with_progress(prefetched_snapshot))

        assert stats["total"] == 5
        assert stats["succeeded"] == 1
        assert stats["running"] == 1
        assert stats["pending"] == 3
        assert stats["percent"] == 20
        assert "1/5 hooks" in html

    def test_get_progress_stats_sealed(self, snapshot):
        """Test progress stats for sealed snapshot."""
        from archivebox.core.models import Snapshot

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save()

        stats = snapshot.get_progress_stats()
        assert stats["is_sealed"] is True

    def test_archive_size_uses_materialized_output_size_without_output_dir(self, snapshot, monkeypatch, django_capture_on_commit_callbacks):
        """archive_size should trust the materialized DB size without touching disk."""
        from archivebox.core.models import ArchiveResult, Snapshot

        with django_capture_on_commit_callbacks(execute=True):
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="wget",
                status="succeeded",
                output_size=4096,
            )
        snapshot.refresh_from_db(fields=["output_size"])

        def _output_dir_should_not_be_used(self):
            raise AssertionError("archive_size should not access Snapshot.output_dir when results are prefetched")

        monkeypatch.setattr(Snapshot, "output_dir", property(_output_dir_should_not_be_used), raising=False)

        assert snapshot.archive_size == 4096

    def test_snapshot_serialization_exposes_output_size_alias(self, snapshot, django_capture_on_commit_callbacks):
        """Snapshot serializers should expose output_size as an alias of archive_size."""
        from archivebox.core.models import ArchiveResult

        with django_capture_on_commit_callbacks(execute=True):
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="wget",
                status="succeeded",
                output_size=4096,
            )
        snapshot.refresh_from_db(fields=["output_size"])

        assert snapshot.to_dict()["archive_size"] == 4096
        assert snapshot.to_dict()["output_size"] == 4096
        assert snapshot.to_dict()["status"] == snapshot.status
        assert snapshot.to_json()["archive_size"] == 4096
        assert snapshot.to_json()["output_size"] == 4096
        assert snapshot.to_csv(cols=["output_size"]) == "4096"
        assert snapshot.to_csv(cols=["status"]) == '"started"'

    def test_is_archived_true_for_sealed_snapshot_without_legacy_output_paths(self, snapshot, monkeypatch):
        """Sealed snapshots should count as archived without relying on legacy output filenames."""
        from archivebox.core.models import Snapshot

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save(update_fields=["status", "modified_at"])

        def _missing_output_dir(self):
            return Path("/definitely/missing")

        monkeypatch.setattr(Snapshot, "output_dir", property(_missing_output_dir), raising=False)

        assert snapshot.is_archived is True

    def test_discover_outputs_uses_output_file_metadata_size(self, snapshot):
        """discover_outputs should use output_files metadata before filesystem fallbacks."""
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "ytdlp"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "video.mp4").write_bytes(b"video")

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_str="",
            output_files={"video.mp4": {"size": 9876, "mimetype": "video/mp4", "extension": "mp4"}},
            output_size=0,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)
        ytdlp_output = next(output for output in outputs if output["name"] == "ytdlp")

        assert ytdlp_output["path"] == "ytdlp/video.mp4"
        assert ytdlp_output["size"] == 9876

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

    def test_ytdlp_discover_outputs_prefers_video_over_thumbnail(self, snapshot):
        """YT-DLP snapshot cards should preview playable media before thumbnails."""
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_files={
                "thumbnail.jpg": {"size": 9999, "mimetype": "image/jpeg", "extension": "jpg"},
                "video.mp4": {"size": 111, "mimetype": "video/mp4", "extension": "mp4"},
            },
            output_size=10110,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)
        ytdlp_output = next(output for output in outputs if output["name"] == "ytdlp")

        assert ytdlp_output["path"] == "ytdlp/video.mp4"

    def test_ytdlp_discover_outputs_prefers_browser_playable_video(self, snapshot):
        """YT-DLP snapshot cards should not pick larger non-browser video over playable video."""
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_files={
                "large.mkv": {"size": 9999, "mimetype": "video/x-matroska", "extension": "mkv"},
                "small.mp4": {"size": 111, "mimetype": "video/mp4", "extension": "mp4"},
            },
            output_size=10110,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)
        ytdlp_output = next(output for output in outputs if output["name"] == "ytdlp")

        assert ytdlp_output["path"] == "ytdlp/small.mp4"

    def test_ytdlp_plugin_card_renders_video_player(self, snapshot):
        """YT-DLP cards should play archived videos inline instead of only listing downloads."""
        from archivebox.core.models import ArchiveResult
        from archivebox.core.templatetags import core_tags

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_files={"video.mp4": {"size": 111, "mimetype": "video/mp4", "extension": "mp4"}},
            output_size=111,
        )

        html = str(core_tags.plugin_card({"request": None, "CONFIG": None}, result))

        assert "<video" in html
        assert "controls" in html
        assert "ytdlp/video.mp4" in html

    def test_ytdlp_plugin_card_links_non_browser_video_without_player(self, snapshot):
        """Non-browser-playable videos should remain downloadable without rendering broken players."""
        from archivebox.core.models import ArchiveResult
        from archivebox.core.templatetags import core_tags

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="ytdlp",
            status="succeeded",
            output_files={"video.mkv": {"size": 111, "mimetype": "video/x-matroska", "extension": "mkv"}},
            output_size=111,
        )

        html = str(core_tags.plugin_card({"request": None, "CONFIG": None}, result))

        assert "<video" not in html
        assert "<audio" not in html
        assert "ytdlp/video.mkv" in html

    def test_discover_outputs_falls_back_to_hashes_index_without_filesystem_walk(self, snapshot):
        """Older snapshots can still render cards from hashes.json when DB output_files are missing."""
        import json

        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            status="succeeded",
            output_str="141 responses",
            output_files={},
        )

        hashes_dir = Path(snapshot.output_dir) / "hashes"
        hashes_dir.mkdir(parents=True, exist_ok=True)
        (hashes_dir / "hashes.json").write_text(
            json.dumps(
                {
                    "responses/index.jsonl": {"size": 456},
                    "responses/all/20260323T073504__GET__example.com__.html": {"size": 789},
                    "responses/all/20260323T073504__GET__example.com__app.js": {"size": 123},
                },
            ),
            encoding="utf-8",
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=True)

        assert next(output for output in outputs if output["name"] == "responses")["path"] == (
            "responses/all/20260323T073504__GET__example.com__.html"
        )

    def test_discover_outputs_falls_back_to_filesystem_for_missing_db_and_hashes(self, snapshot):
        """Snapshot page can still recover cards from plugin dirs when DB metadata is missing."""
        responses_dir = Path(snapshot.output_dir) / "responses"
        (responses_dir / "all").mkdir(parents=True, exist_ok=True)
        (responses_dir / "index.jsonl").write_text("{}", encoding="utf-8")
        (responses_dir / "all" / "20260323T073504__GET__example.com__.html").write_text("<html>ok</html>", encoding="utf-8")

        outputs = snapshot.discover_outputs(include_filesystem_fallback=True)

        assert next(output for output in outputs if output["name"] == "responses")["path"] == (
            "responses/all/20260323T073504__GET__example.com__.html"
        )

    def test_embed_path_db_ignores_human_readable_output_messages(self, snapshot):
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            status="failed",
            output_str="SingleFile extension did not produce output",
        )

        assert result.embed_path_db() is None

    def test_embed_path_db_prefers_valid_output_str_over_first_output_file(self, snapshot):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "wget" / "example.com" / "assets" / "css"
        output_dir.mkdir(parents=True, exist_ok=True)
        (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").parent.mkdir(parents=True, exist_ok=True)
        (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
        (output_dir / "mobile.css").write_text("body {}", encoding="utf-8")

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status="succeeded",
            output_str="wget/example.com/index.html",
            output_files={
                "example.com/assets/css/mobile.css": {"size": 123, "mimetype": "text/css"},
                "example.com/index.html": {"size": 456, "mimetype": "text/html"},
            },
        )

        assert result.embed_path_db() == "wget/example.com/index.html"

    def test_embed_path_db_scores_output_files_instead_of_using_first_entry(self, snapshot):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "wget" / "example.com" / "assets" / "css"
        output_dir.mkdir(parents=True, exist_ok=True)
        (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").parent.mkdir(parents=True, exist_ok=True)
        (Path(snapshot.output_dir) / "wget" / "example.com" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
        (output_dir / "mobile.css").write_text("body {}", encoding="utf-8")

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status="succeeded",
            output_str="",
            output_files={
                "example.com/assets/css/mobile.css": {"size": 123, "mimetype": "text/css"},
                "example.com/index.html": {"size": 456, "mimetype": "text/html"},
            },
        )

        assert result.embed_path_db() == "wget/example.com/index.html"

    def test_embed_path_db_rejects_mimetype_like_output_str(self, snapshot):
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="staticfile",
            status="succeeded",
            output_str="text/html",
        )

        assert result.embed_path_db() is None

    def test_embed_path_db_rejects_output_str_that_does_not_exist_on_disk(self, snapshot):
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dns",
            status="succeeded",
            output_str="1.2.3.4",
        )

        assert result.embed_path_db() is None

    def test_embed_path_db_uses_output_file_fallbacks_without_disk_check(self, snapshot):
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            status="succeeded",
            output_str="",
            output_files={
                "all/20260323T073504__GET__example.com__.html": {"size": 789, "mimetype": "text/html"},
            },
        )

        assert result.embed_path_db() == "responses/all/20260323T073504__GET__example.com__.html"

    def test_discover_outputs_keeps_jsonl_only_plugins_with_non_path_output_str(self, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dns",
            status="succeeded",
            output_str="1.2.3.4",
            output_files={"dns.jsonl": {"size": 1519, "mimetype": "application/jsonl"}},
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="sslcerts",
            status="succeeded",
            output_str="WR2",
            output_files={"sslcerts.jsonl": {"size": 3138, "mimetype": "application/jsonl"}},
        )

        outputs = {output["name"]: output for output in snapshot.discover_outputs(include_filesystem_fallback=False)}

        assert outputs["dns"]["path"] == "dns/dns.jsonl"
        assert outputs["sslcerts"]["path"] == "sslcerts/sslcerts.jsonl"
        assert outputs["dns"]["is_metadata"] is True
        assert outputs["sslcerts"]["is_metadata"] is True

    def test_embed_path_uses_explicit_fallback_not_first_output_file(self, snapshot):
        from archivebox.core.models import ArchiveResult

        output_dir = Path(snapshot.output_dir) / "responses" / "all"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "20260323T073504__GET__example.com__.html").write_text("<html>ok</html>", encoding="utf-8")

        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            status="succeeded",
            output_str="141 responses",
            output_files={
                "all/20260323T073504__GET__example.com__app.js": {"size": 123, "mimetype": "application/javascript"},
                "all/20260323T073504__GET__example.com__.html": {"size": 789, "mimetype": "text/html"},
                "index.jsonl": {"size": 456, "mimetype": "application/jsonl"},
            },
        )

        assert result.embed_path_db() == "responses/all/20260323T073504__GET__example.com__.html"
        assert result.embed_path() == "responses/all/20260323T073504__GET__example.com__.html"

    def test_detail_page_auxiliary_items_include_failed_plugins(self, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            status=ArchiveResult.StatusChoices.FAILED,
            output_str="SingleFile extension did not produce output",
        )

        loose_items, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[])

        assert loose_items == []
        assert failed_items == [
            {
                "name": "singlefile (failed)",
                "path": "singlefile",
                "is_dir": True,
                "size": 0,
            },
        ]

    def test_detail_page_auxiliary_items_include_hidden_failed_plugins(self, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="favicon",
            status=ArchiveResult.StatusChoices.FAILED,
            output_str="No favicon found",
        )

        _, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[], hidden_card_plugins={"favicon"})

        assert failed_items == [
            {
                "name": "favicon (failed)",
                "path": "favicon",
                "is_dir": True,
                "size": 0,
            },
        ]

    def test_detail_page_auxiliary_items_exclude_noresults_and_skipped(self, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            status=ArchiveResult.StatusChoices.NORESULTS,
            output_str="No title found",
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="favicon",
            status=ArchiveResult.StatusChoices.SKIPPED,
            output_str="Skipped",
        )

        _, failed_items = snapshot.get_detail_page_auxiliary_items(outputs=[])

        assert failed_items == []

    def test_plugin_full_prefers_db_embed_path_over_empty_filesystem_embed_path(self, snapshot, monkeypatch):
        from archivebox.core.templatetags import core_tags
        from archivebox.core.models import ArchiveResult

        result = ArchiveResult.objects.create(
            plugin="title",
            snapshot=snapshot,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"title.txt": {"size": 12, "extension": "txt", "mimetype": "text/plain"}},
        )

        monkeypatch.setattr(core_tags, "get_plugin_template", lambda plugin, view: "{{ output_path }}")

        html = str(core_tags.plugin_full({"request": None}, result))

        assert "title/title.txt" in html
        assert "?preview=1" not in html
        assert html != "http://snap-ffa4215f6d64.archivebox.localhost:8000"

    def test_plugin_full_returns_empty_for_none_result(self):
        from archivebox.core.templatetags import core_tags

        assert core_tags.plugin_full({"request": None}, None) == ""

    def test_write_html_details_succeeds_with_index_only_fallback_output(self, snapshot):
        output_dir = Path(snapshot.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.jsonl").write_text('{"type":"Snapshot"}\n', encoding="utf-8")

        snapshot.write_html_details()

        rendered = (output_dir / "index.html").read_text(encoding="utf-8")

        assert "full-page-iframe" in rendered
        assert "index.jsonl?preview=1" in rendered


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

    def test_list_view_avoids_legacy_title_fallbacks(self, client, admin_user, snapshot, monkeypatch):
        """Title-less snapshots should render without touching history-based fallback paths."""
        from archivebox.core.models import Snapshot

        Snapshot.objects.filter(pk=snapshot.pk).update(title="")

        def _latest_title_should_not_be_used(self):
            raise AssertionError("admin changelist should not access Snapshot.latest_title")

        def _history_should_not_be_used(self):
            raise AssertionError("admin changelist should not access Snapshot.history")

        monkeypatch.setattr(Snapshot, "latest_title", property(_latest_title_should_not_be_used), raising=False)
        monkeypatch.setattr(Snapshot, "history", property(_history_should_not_be_used), raising=False)

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_list_view_avoids_output_dir_lookups(self, client, admin_user, snapshot, monkeypatch):
        """Changelist links should render without probing snapshot paths on disk."""
        from archivebox.core.models import Snapshot

        def _output_dir_should_not_be_used(self):
            raise AssertionError("admin changelist should not access Snapshot.output_dir")

        monkeypatch.setattr(Snapshot, "output_dir", property(_output_dir_should_not_be_used), raising=False)

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_list_view_avoids_snapshot_icons_helper(self, client, admin_user, snapshot, monkeypatch):
        """Changelist should not call Snapshot.icons for each row anymore."""
        from archivebox.core.models import ArchiveResult, Snapshot

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={"index.html": {"size": 123, "extension": "html"}},
        )

        def _icons_should_not_be_used(self, path=None):
            raise AssertionError("admin changelist should not call Snapshot.icons")

        monkeypatch.setattr(Snapshot, "icons", _icons_should_not_be_used, raising=True)

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"wget" in response.content

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

    def test_grid_view_renders(self, client, admin_user):
        """Test that the grid view renders successfully."""
        client.force_login(admin_user)
        url = reverse("admin:grid")
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200

    def test_grid_card_component_order(self, client, admin_user, snapshot):
        """Snapshot cards should keep metadata, title, URL, preview, and outputs in scan order."""
        from archivebox.core.models import ArchiveResult, Tag

        snapshot.title = "Example Snapshot"
        snapshot.status = snapshot.StatusChoices.SEALED
        snapshot.save(update_fields=["title", "status", "modified_at"])
        snapshot.tags.add(Tag.objects.create(name="research"))
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dom",
            status="succeeded",
            output_size=1000,
            output_files={"output.html": {"path": "output.html", "size": 1000}},
        )

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

    def test_snapshot_view_url_uses_canonical_replay_url_for_mode(self, snapshot, monkeypatch):
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.core.admin_snapshots import SnapshotAdmin
        from archivebox.config.common import get_config

        admin = SnapshotAdmin(snapshot.__class__, archivebox_admin)

        monkeypatch.setenv("SERVER_SECURITY_MODE", "safe-subdomains-fullreplay")
        request = RequestFactory().get("/", HTTP_HOST="admin.archivebox.localhost:8000")
        request.archivebox_config = get_config()
        admin.request = request
        assert admin.get_snapshot_view_url(snapshot) == f"http://snap-{str(snapshot.pk).replace('-', '')[-12:]}.archivebox.localhost:8000"

        monkeypatch.setenv("SERVER_SECURITY_MODE", "safe-onedomain-nojsreplay")
        request.archivebox_config = get_config()
        assert admin.get_snapshot_view_url(snapshot) == f"http://archivebox.localhost:8000/snapshot/{snapshot.pk}"

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

    def test_redo_failed_action_requeues_snapshot(self, client, admin_user, snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__54_title",
            status=ArchiveResult.StatusChoices.FAILED,
            output_str="boom",
        )

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_redo_failed", args=[snapshot.pk])
        response = client.post(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 302
        assert response["Location"].endswith(f"/admin/core/snapshot/{snapshot.pk}/change/")
        assert snapshot.archiveresult_set.get(plugin="title").status == ArchiveResult.StatusChoices.QUEUED

    def test_list_redo_failed_action_requeues_failed_archiveresults_only(self, client, admin_user, snapshot):
        from archivebox.core.models import ArchiveResult

        failed = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__50_wget",
            status=ArchiveResult.StatusChoices.FAILED,
            output_str="boom",
            output_files={"index.html": {"path": "index.html", "size": 123}},
            output_size=123,
            output_mimetypes="text/html",
        )
        succeeded = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__54_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="Example Domain",
        )

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
        assert failed.status == ArchiveResult.StatusChoices.QUEUED
        assert failed.output_str == ""
        assert failed.output_files == {}
        assert failed.output_size == 0
        assert failed.output_mimetypes == ""
        assert succeeded.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert succeeded.output_str == "Example Domain"
        assert snapshot.status == snapshot.StatusChoices.QUEUED

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

    def test_change_view_archiveresults_inline_shows_process_and_machine_links(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        process = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            pid=54321,
            exit_code=0,
            cmd=["/plugins/title/on_Snapshot__54_title.js", "--url=https://example.com"],
            env={"EXTRA_CONTEXT": json.dumps({"snapshot_id": str(snapshot.id)})},
            started_at=timezone.now(),
            ended_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            process=process,
            plugin="title",
            hook_name="on_Snapshot__54_title.js",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="Example Domain",
        )

        client.force_login(admin_user)
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Process" in response.content
        assert b"Machine" in response.content
        assert b"54321" in response.content
        assert machine.hostname.encode() in response.content
        assert reverse("admin:machine_process_change", args=[process.id]).encode() in response.content
        assert reverse("admin:machine_machine_change", args=[machine.id]).encode() in response.content
