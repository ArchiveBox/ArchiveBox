"""
Tests for admin snapshot views and search functionality.

Tests cover:
- Admin snapshot list view
- Admin grid view
- Search functionality (both admin and public)
- Snapshot progress statistics
"""

import pytest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.utils import timezone

from archivebox.config.common import SEARCH_BACKEND_CONFIG

pytestmark = pytest.mark.django_db


User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:8000"
PUBLIC_HOST = "public.archivebox.localhost:8000"


@pytest.fixture
def admin_user(db):
    """Create admin user for tests."""
    return cast(UserManager, User.objects).create_superuser(
        username="testadmin",
        email="admin@test.com",
        password="testpassword",
    )


@pytest.fixture
def crawl(admin_user, db):
    """Create test crawl."""
    from archivebox.crawls.models import Crawl

    return Crawl.objects.create(
        urls="https://example.com",
        created_by=admin_user,
    )


@pytest.fixture
def snapshot(crawl, db):
    """Create test snapshot."""
    from archivebox.core.models import Snapshot

    return Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


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

    def test_archive_size_uses_prefetched_results_without_output_dir(self, snapshot, monkeypatch):
        """archive_size should use prefetched ArchiveResult sizes before touching disk."""
        from archivebox.core.models import ArchiveResult, Snapshot

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status="succeeded",
            output_size=4096,
        )

        prefetched_snapshot = Snapshot.objects.prefetch_related("archiveresult_set").get(pk=snapshot.pk)

        def _output_dir_should_not_be_used(self):
            raise AssertionError("archive_size should not access Snapshot.output_dir when results are prefetched")

        monkeypatch.setattr(Snapshot, "output_dir", property(_output_dir_should_not_be_used), raising=False)

        assert prefetched_snapshot.archive_size == 4096

    def test_snapshot_serialization_exposes_output_size_alias(self, snapshot):
        """Snapshot serializers should expose output_size as an alias of archive_size."""
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            status="succeeded",
            output_size=4096,
        )

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
            {"name": "audio.mp3", "path": "ytdlp/audio.mp3", "size": 222},
            {"name": "video.mp4", "path": "ytdlp/video.mp4", "size": 111},
        ]

    def test_discover_outputs_falls_back_to_hashes_index_without_filesystem_walk(self, snapshot, monkeypatch):
        """Older snapshots can still render cards from hashes.json when DB output_files are missing."""
        from archivebox.core.models import ArchiveResult, Snapshot

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="responses",
            status="succeeded",
            output_str="141 responses",
            output_files={},
        )

        monkeypatch.setattr(
            Snapshot,
            "hashes_index",
            property(
                lambda self: {
                    "responses/index.jsonl": {"size": 456},
                    "responses/all/20260323T073504__GET__example.com__.html": {"size": 789},
                    "responses/all/20260323T073504__GET__example.com__app.js": {"size": 123},
                },
            ),
            raising=False,
        )

        outputs = snapshot.discover_outputs(include_filesystem_fallback=False)

        assert next(output for output in outputs if output["name"] == "responses")["path"] == (
            "responses/all/20260323T073504__GET__example.com__.html"
        )

    def test_discover_outputs_falls_back_to_filesystem_for_missing_db_and_hashes(self, snapshot, monkeypatch):
        """Snapshot page can still recover cards from plugin dirs when DB metadata is missing."""
        from archivebox.core.models import Snapshot

        monkeypatch.setattr(Snapshot, "hashes_index", property(lambda self: {}), raising=False)

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

    def test_plugin_full_prefers_db_embed_path_over_empty_filesystem_embed_path(self, monkeypatch):
        from archivebox.core.templatetags import core_tags

        result = SimpleNamespace(
            plugin="title",
            snapshot=SimpleNamespace(),
            snapshot_id="019d191c-5e42-77fc-b5b6-ffa4215f6d64",
            embed_path_db=lambda: "title/title.txt",
            embed_path=lambda: None,
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
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_list_view_with_snapshots(self, client, admin_user, snapshot):
        """Test list view with snapshots displays them."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_live_progress_excludes_old_archiveresults_from_previous_snapshot_run(self, client, admin_user, crawl, snapshot):
        from datetime import timedelta
        from archivebox.core.models import ArchiveResult
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        client.login(username="testadmin", password="testpassword")

        now = timezone.now()
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
            modified_at=now,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
            downloaded_at=now - timedelta(minutes=1),
            modified_at=now,
        )

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget.finite.bg",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=now - timedelta(hours=1, minutes=1),
            end_ts=now - timedelta(hours=1),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="chrome",
            hook_name="on_Snapshot__11_chrome_wait",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        response = client.get("/admin/live-progress/", HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(item for item in payload["active_crawls"] if item["id"] == str(crawl.pk))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.pk))
        plugin_names = [item["plugin"] for item in active_snapshot["all_plugins"]]
        assert plugin_names == ["chrome"]

    def test_live_progress_does_not_hide_active_snapshot_results_when_modified_at_moves(self, client, admin_user, crawl, snapshot):
        from datetime import timedelta
        from archivebox.core.models import ArchiveResult
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        client.login(username="testadmin", password="testpassword")

        now = timezone.now()
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
            modified_at=now,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
            created_at=now - timedelta(hours=2),
            modified_at=now,
            downloaded_at=None,
        )

        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget.finite.bg",
            status=ArchiveResult.StatusChoices.STARTED,
            start_ts=now - timedelta(minutes=5),
        )

        response = client.get("/admin/live-progress/", HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(item for item in payload["active_crawls"] if item["id"] == str(crawl.pk))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.pk))
        plugin_names = [item["plugin"] for item in active_snapshot["all_plugins"]]
        assert plugin_names == ["wget"]

    def test_list_view_avoids_output_dir_lookups(self, client, admin_user, snapshot, monkeypatch):
        """Changelist links should render without probing snapshot paths on disk."""
        from archivebox.core.models import Snapshot

        def _output_dir_should_not_be_used(self):
            raise AssertionError("admin changelist should not access Snapshot.output_dir")

        monkeypatch.setattr(Snapshot, "output_dir", property(_output_dir_should_not_be_used), raising=False)

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        per_row_tag_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if 'FROM "core_tag"' in query["sql"] and '"core_snapshot_tags"."snapshot_id"' in query["sql"] and " IN " not in query["sql"]
        ]
        assert per_row_tag_queries == []

    def test_grid_view_renders(self, client, admin_user):
        """Test that the grid view renders successfully."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:grid")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_view_mode_switcher_present(self, client, admin_user):
        """Test that view mode switcher is present."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        # Check for visible snapshot actions-bar controls
        assert b"snapshot-view-toggle" in response.content
        assert b"Grid" in response.content
        assert reverse("admin:grid").encode() in response.content

    def test_binary_change_view_renders(self, client, admin_user, db):
        """Binary admin change form should load without FieldError."""
        from archivebox.machine.models import Machine, Binary

        machine = Machine.objects.create(
            guid=f"test-guid-{uuid.uuid4()}",
            hostname="test-host",
            hw_in_docker=False,
            hw_in_vm=False,
            hw_manufacturer="Test",
            hw_product="Test Product",
            hw_uuid=f"test-hw-{uuid.uuid4()}",
            os_arch="x86_64",
            os_family="darwin",
            os_platform="darwin",
            os_release="test",
            os_kernel="test-kernel",
            stats={},
        )
        binary = Binary.objects.create(
            machine=machine,
            name="gallery-dl",
            binproviders="env",
            binprovider="env",
            abspath="/opt/homebrew/bin/gallery-dl",
            version="1.26.9",
            sha256="abc123",
            status=Binary.StatusChoices.INSTALLED,
        )

        client.login(username="testadmin", password="testpassword")
        url = f"/admin/machine/binary/{binary.pk}/change/"
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"gallery-dl" in response.content

    def test_process_change_view_renders_copyable_cmd_env_and_readonly_runtime_fields(self, client, admin_user, db):
        from datetime import timedelta
        from archivebox.machine.models import Machine, Process

        machine = Machine.objects.create(
            guid=f"test-guid-{uuid.uuid4()}",
            hostname="test-host",
            hw_in_docker=False,
            hw_in_vm=False,
            hw_manufacturer="Test",
            hw_product="Test Product",
            hw_uuid=f"test-hw-{uuid.uuid4()}",
            os_arch="x86_64",
            os_family="darwin",
            os_platform="darwin",
            os_release="test",
            os_kernel="test-kernel",
            stats={},
        )
        process = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            pwd="/tmp/archivebox",
            cmd=["python", "/tmp/job.py", "--url=https://example.com"],
            env={
                "SNAPSHOT_ID": "abc123",
                "ENABLED": True,
                "API_KEY": "super-secret-key",
                "ACCESS_TOKEN": "super-secret-token",
                "SHARED_SECRET": "super-secret-secret",
            },
            timeout=90,
            pid=54321,
            exit_code=0,
            url="https://example.com/status",
            started_at=timezone.now() - timedelta(seconds=52),
            ended_at=timezone.now(),
        )

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:machine_process_change", args=[process.pk])
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Kill" in response.content
        assert b"python /tmp/job.py --url=https://example.com" in response.content
        assert b"SNAPSHOT_ID=abc123" in response.content
        assert b"ENABLED=True" in response.content
        assert b"52s" in response.content
        assert b"API_KEY=" not in response.content
        assert b"ACCESS_TOKEN=" not in response.content
        assert b"SHARED_SECRET=" not in response.content
        assert b"super-secret-key" not in response.content
        assert b"super-secret-token" not in response.content
        assert b"super-secret-secret" not in response.content
        assert response.content.count(b"data-command=") >= 2
        assert b'name="timeout"' not in response.content
        assert b'name="pid"' not in response.content
        assert b'name="exit_code"' not in response.content
        assert b'name="url"' not in response.content
        assert b'name="started_at"' not in response.content
        assert b'name="ended_at"' not in response.content

    def test_process_list_view_shows_duration_snapshot_and_crawl_columns(self, client, admin_user, snapshot, db):
        from datetime import timedelta
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        machine = Machine.objects.create(
            guid=f"list-guid-{uuid.uuid4()}",
            hostname="list-host",
            hw_in_docker=False,
            hw_in_vm=False,
            hw_manufacturer="Test",
            hw_product="Test Product",
            hw_uuid=f"list-hw-{uuid.uuid4()}",
            os_arch="x86_64",
            os_family="darwin",
            os_platform="darwin",
            os_release="test",
            os_kernel="test-kernel",
            stats={},
        )
        process = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            pwd="/tmp/archivebox",
            cmd=["python", "/tmp/job.py"],
            env={},
            pid=12345,
            exit_code=0,
            started_at=timezone.now() - timedelta(milliseconds=10),
            ended_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            process=process,
            plugin="title",
            hook_name="on_Snapshot__54_title",
            status="succeeded",
            output_str="Example Domain",
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:machine_process_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Duration" in response.content
        assert b"Snapshot" in response.content
        assert b"Crawl" in response.content
        assert b"0.01s" in response.content
        changelist = response.context["cl"]
        row = next(obj for obj in changelist.result_list if obj.pk == process.pk)

        assert row.archiveresult.snapshot_id == snapshot.id
        assert str(snapshot.id) in str(changelist.model_admin.snapshot_link(row))
        assert str(snapshot.crawl_id) in str(changelist.model_admin.crawl_link(row))

    def test_change_view_renders_real_redo_failed_action(self, client, admin_user, snapshot):
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert f"/admin/core/snapshot/{snapshot.pk}/redo-failed/".encode() in response.content

    def test_snapshot_view_url_uses_canonical_replay_url_for_mode(self, snapshot, monkeypatch):
        from archivebox.config.common import SERVER_CONFIG
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.core.admin_snapshots import SnapshotAdmin

        admin = SnapshotAdmin(snapshot.__class__, archivebox_admin)

        monkeypatch.setattr(SERVER_CONFIG, "SERVER_SECURITY_MODE", "safe-subdomains-fullreplay")
        assert admin.get_snapshot_view_url(snapshot) == f"http://snap-{str(snapshot.pk).replace('-', '')[-12:]}.archivebox.localhost:8000"

        monkeypatch.setattr(SERVER_CONFIG, "SERVER_SECURITY_MODE", "safe-onedomain-nojsreplay")
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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_redo_failed", args=[snapshot.pk])
        response = client.post(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 302
        assert response["Location"].endswith(f"/admin/core/snapshot/{snapshot.pk}/change/")
        assert snapshot.archiveresult_set.get(plugin="title").status == ArchiveResult.StatusChoices.QUEUED

    def test_archive_now_action_uses_original_snapshot_url_without_timestamp_suffix(self, client, admin_user, snapshot, monkeypatch):
        import archivebox.core.admin_snapshots as admin_snapshots

        snapshot.url = "https://example.com/path#section-1"
        snapshot.save(update_fields=["url"])

        queued = []

        def fake_bg_add(payload):
            queued.append(payload)

        monkeypatch.setattr(admin_snapshots, "bg_add", fake_bg_add)

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.post(
            url,
            {
                "action": "resnapshot_snapshot",
                "_selected_action": [str(snapshot.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 302
        assert queued == [{"urls": "https://example.com/path#section-1"}]

    def test_archive_now_action_groups_multiple_snapshots_into_one_crawl(self, client, admin_user, snapshot, monkeypatch):
        import archivebox.core.admin_snapshots as admin_snapshots
        from archivebox.core.models import Snapshot

        other_snapshot = Snapshot.objects.create(
            url="https://example.com/other#frag",
            crawl=snapshot.crawl,
            status=Snapshot.StatusChoices.STARTED,
        )

        queued = []

        def fake_bg_add(payload):
            queued.append(payload)

        monkeypatch.setattr(admin_snapshots, "bg_add", fake_bg_add)

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.post(
            url,
            {
                "action": "resnapshot_snapshot",
                "_selected_action": [str(snapshot.pk), str(other_snapshot.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 302
        assert len(queued) == 1
        assert set(queued[0]["urls"].splitlines()) == {"https://example.com", "https://example.com/other#frag"}

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
            env={"SNAPSHOT_ID": str(snapshot.id)},
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

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_change", args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Process" in response.content
        assert b"Machine" in response.content
        assert b"54321" in response.content
        assert machine.hostname.encode() in response.content
        assert reverse("admin:machine_process_change", args=[process.id]).encode() in response.content
        assert reverse("admin:machine_machine_change", args=[machine.id]).encode() in response.content


class TestCrawlScheduleAdmin:
    def test_crawlschedule_add_view_renders_and_saves(self, client, admin_user, crawl):
        from archivebox.crawls.models import CrawlSchedule

        client.login(username="testadmin", password="testpassword")

        add_url = reverse("admin:crawls_crawlschedule_add")
        get_response = client.get(add_url, HTTP_HOST=ADMIN_HOST)

        assert get_response.status_code == 200
        assert b"Schedule Info" in get_response.content
        assert b"No Crawls yet..." not in get_response.content
        assert b"No Snapshots yet..." not in get_response.content

        post_response = client.post(
            add_url,
            {
                "label": "Nightly crawl",
                "notes": "",
                "schedule": "0 0 * * *",
                "template": str(crawl.pk),
                "created_by": str(admin_user.pk),
                "_save": "Save",
            },
            HTTP_HOST=ADMIN_HOST,
        )

        assert post_response.status_code == 302
        schedule = CrawlSchedule.objects.get(label="Nightly crawl")
        assert schedule.template_id == crawl.pk
        assert schedule.created_by_id == admin_user.pk

    def test_crawlschedule_changelist_renders_snapshot_counts(self, client, admin_user, crawl, snapshot):
        from archivebox.crawls.models import CrawlSchedule

        schedule = CrawlSchedule.objects.create(
            label="Daily crawl",
            notes="",
            schedule="0 0 * * *",
            template=crawl,
            created_by=admin_user,
        )
        crawl.schedule = schedule
        crawl.save(update_fields=["schedule"])
        snapshot.crawl = crawl
        snapshot.save(update_fields=["crawl"])

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:crawls_crawlschedule_changelist")
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Daily crawl" in response.content


class TestArchiveResultAdminListView:
    def test_list_view_renders_readonly_tags_and_noresults_status(self, client, admin_user, snapshot):
        from archivebox.core.models import ArchiveResult, Tag

        tag = Tag.objects.create(name="Alpha Research")
        snapshot.tags.add(tag)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            status=ArchiveResult.StatusChoices.NORESULTS,
            output_str="No title found",
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_archiveresult_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Alpha Research" in response.content
        assert b"tag-editor-inline readonly" in response.content
        assert b"No Results" in response.content

    def test_api_token_admin_list_view_renders(self, client, admin_user):
        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:api_apitoken_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"API Keys" in response.content

    def test_user_admin_list_view_renders(self, client, admin_user):
        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:auth_user_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"Select user to change" in response.content

    def test_archiveresult_model_has_no_retry_at_field(self):
        from archivebox.core.models import ArchiveResult

        assert "retry_at" not in {field.name for field in ArchiveResult._meta.fields}


class TestLiveProgressView:
    def test_live_progress_ignores_unscoped_running_processes_when_no_crawls(self, client, admin_user, db):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            cmd=["/plugins/title/on_Snapshot__10_title.py", "--url=https://example.com"],
            env={},
            started_at=timezone.now(),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        assert payload["active_crawls"] == []
        assert payload["total_workers"] == 0

    def test_live_progress_cleans_stale_running_processes(self, client, admin_user, db):
        from datetime import timedelta
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        proc = Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=999999,
            cmd=["/plugins/title/on_Snapshot__10_title.py", "--url=https://example.com"],
            env={},
            started_at=timezone.now() - timedelta(days=2),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.EXITED
        assert proc.ended_at is not None
        assert response.json()["total_workers"] == 0

    def test_live_progress_routes_crawl_process_rows_to_crawl_setup(self, client, admin_user, snapshot, db):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        pid = os.getpid()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            cmd=["/plugins/chrome/on_Crawl__91_chrome_wait.js", "--url=https://example.com"],
            env={
                "CRAWL_ID": str(snapshot.crawl_id),
                "SNAPSHOT_ID": str(snapshot.id),
            },
            started_at=timezone.now(),
        )

        client.login(username="testadmin", password="testpassword")
        with (
            patch.object(Process, "cleanup_stale_running", return_value=0),
            patch.object(Process, "cleanup_orphaned_workers", return_value=0),
        ):
            response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        setup_entry = next(item for item in active_crawl["setup_plugins"] if item["source"] == "process")
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        assert setup_entry["label"] == "chrome wait"
        assert setup_entry["status"] == "started"
        assert active_crawl["worker_pid"] == pid
        assert active_snapshot["all_plugins"] == []

    def test_live_progress_uses_snapshot_process_rows_before_archiveresults(self, client, admin_user, snapshot, db):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        pid = os.getpid()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=pid,
            cmd=["/plugins/title/on_Snapshot__10_title.py", "--url=https://example.com"],
            env={
                "CRAWL_ID": str(snapshot.crawl_id),
                "SNAPSHOT_ID": str(snapshot.id),
            },
            started_at=timezone.now(),
        )

        client.login(username="testadmin", password="testpassword")
        with (
            patch.object(Process, "cleanup_stale_running", return_value=0),
            patch.object(Process, "cleanup_orphaned_workers", return_value=0),
        ):
            response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        assert active_snapshot["all_plugins"][0]["source"] == "process"
        assert active_snapshot["all_plugins"][0]["label"] == "title"
        assert active_snapshot["all_plugins"][0]["status"] == "started"
        assert active_snapshot["worker_pid"] == pid

    def test_live_progress_merges_process_rows_with_archiveresults_when_present(self, client, admin_user, snapshot, db):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            cmd=["/plugins/chrome/on_Snapshot__11_chrome_wait.js", "--url=https://example.com"],
            env={
                "CRAWL_ID": str(snapshot.crawl_id),
                "SNAPSHOT_ID": str(snapshot.id),
            },
            started_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            status=ArchiveResult.StatusChoices.STARTED,
        )

        client.login(username="testadmin", password="testpassword")
        with (
            patch.object(Process, "cleanup_stale_running", return_value=0),
            patch.object(Process, "cleanup_orphaned_workers", return_value=0),
        ):
            response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        sources = {item["source"] for item in active_snapshot["all_plugins"]}
        plugins = {item["plugin"] for item in active_snapshot["all_plugins"]}
        assert sources == {"archiveresult", "process"}
        assert "title" in plugins
        assert "chrome" in plugins

    def test_live_progress_omits_pid_for_exited_process_rows(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            exit_code=0,
            pid=99999,
            cmd=["/plugins/title/on_Snapshot__10_title.py", "--url=https://example.com"],
            env={
                "CRAWL_ID": str(snapshot.crawl_id),
                "SNAPSHOT_ID": str(snapshot.id),
            },
            started_at=timezone.now(),
            ended_at=timezone.now(),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        process_entry = next(item for item in active_snapshot["all_plugins"] if item["source"] == "process")
        assert process_entry["status"] == "succeeded"
        assert "pid" not in process_entry


class TestAdminSnapshotSearch:
    """Tests for admin snapshot search functionality."""

    def test_admin_search_mode_selector_defaults_to_meta_for_ripgrep(self, client, admin_user, monkeypatch):
        monkeypatch.setattr(SEARCH_BACKEND_CONFIG, "SEARCH_BACKEND_ENGINE", "ripgrep")

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'name="search_mode" value="meta" checked' in response.content
        assert b'name="search_mode" value="contents"' in response.content
        assert b'name="search_mode" value="deep"' in response.content

    def test_admin_search_mode_selector_defaults_to_contents_for_non_ripgrep(self, client, admin_user, monkeypatch):
        monkeypatch.setattr(SEARCH_BACKEND_CONFIG, "SEARCH_BACKEND_ENGINE", "sqlite")

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'name="search_mode" value="contents" checked' in response.content

    def test_admin_search_mode_selector_stays_checked_after_search(self, client, admin_user, crawl, monkeypatch):
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        monkeypatch.setattr(
            "archivebox.search.admin.query_search_index",
            lambda query, search_mode=None: Snapshot.objects.all(),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "contents"},
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 200
        assert b'name="search_mode" value="contents" checked' in response.content
        assert b'name="search_mode" value="meta" checked' not in response.content
        assert b'id="changelist"' in response.content
        assert b"search-mode-contents" in response.content

    def test_admin_search_mode_adds_result_tint_class_for_deep(self, client, admin_user, crawl, monkeypatch):
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        monkeypatch.setattr(
            "archivebox.search.admin.query_search_index",
            lambda query, search_mode=None: Snapshot.objects.all(),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "deep"},
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 200
        assert b'name="search_mode" value="deep" checked' in response.content
        assert b"search-mode-deep" in response.content
        assert b"search-rank-" in response.content

    def test_deep_search_assigns_metadata_contents_and_deep_only_ranks(self, client, admin_user, crawl, monkeypatch):
        from archivebox.core.models import Snapshot

        metadata_snapshot = Snapshot.objects.create(
            url="https://example.com/google-meta",
            title="Google Metadata Match",
            crawl=crawl,
        )
        contents_snapshot = Snapshot.objects.create(
            url="https://example.com/contents-only",
            title="Unrelated Title",
            crawl=crawl,
        )
        deep_snapshot = Snapshot.objects.create(
            url="https://example.com/deep-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        def fake_query_search_index(query, search_mode=None):
            if search_mode == "contents":
                return Snapshot.objects.filter(pk=contents_snapshot.pk)
            if search_mode == "deep":
                return Snapshot.objects.filter(pk__in=[contents_snapshot.pk, deep_snapshot.pk])
            return Snapshot.objects.none()

        monkeypatch.setattr("archivebox.search.admin.query_search_index", fake_query_search_index)

        client.login(username="testadmin", password="testpassword")
        response = client.get(
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "deep"},
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 200
        ranks = dict(response.context["cl"].queryset.values_list("pk", "search_rank"))
        assert ranks[metadata_snapshot.pk] == 0
        assert ranks[contents_snapshot.pk] == 1
        assert ranks[deep_snapshot.pk] == 2
        assert b'class="search-rank-0"' in response.content
        assert b'class="search-rank-1"' in response.content
        assert b'class="search-rank-2"' in response.content

    def test_search_ranks_metadata_matches_before_fulltext_by_default(self, client, admin_user, crawl, monkeypatch):
        from archivebox.core.models import Snapshot

        metadata_snapshot = Snapshot.objects.create(
            url="https://example.com/google-meta",
            title="Google Metadata Match",
            crawl=crawl,
        )
        fulltext_snapshot = Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        monkeypatch.setattr(
            "archivebox.search.admin.query_search_index",
            lambda query, search_mode=None: Snapshot.objects.filter(pk=fulltext_snapshot.pk),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": "google", "search_mode": "contents"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        result_ids = list(response.context["cl"].queryset.values_list("pk", flat=True))
        assert result_ids[:2] == [metadata_snapshot.pk, fulltext_snapshot.pk]

    def test_manual_admin_sort_ignores_search_rank_ordering(self, client, admin_user, crawl, monkeypatch):
        from archivebox.core.models import Snapshot

        metadata_snapshot = Snapshot.objects.create(
            url="https://example.com/google-meta",
            title="Google Metadata Match",
            crawl=crawl,
        )
        fulltext_snapshot = Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        monkeypatch.setattr(
            "archivebox.search.admin.query_search_index",
            lambda query, search_mode=None: Snapshot.objects.filter(pk=fulltext_snapshot.pk),
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "contents", "o": "-0"},
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 200
        result_ids = list(response.context["cl"].queryset.values_list("pk", flat=True))
        assert result_ids[:2] == [fulltext_snapshot.pk, metadata_snapshot.pk]

    def test_search_by_url(self, client, admin_user, snapshot):
        """Test searching snapshots by URL."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, {"q": "example.com"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        # The search should find the example.com snapshot
        assert b"example.com" in response.content

    def test_search_by_title(self, client, admin_user, crawl, db):
        """Test searching snapshots by title."""
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://example.com/titled",
            title="Unique Title For Testing",
            crawl=crawl,
        )

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, {"q": "Unique Title"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_search_by_tag(self, client, admin_user, snapshot, db):
        """Test searching snapshots by tag."""
        from archivebox.core.models import Tag

        tag = Tag.objects.create(name="test-search-tag")
        snapshot.tags.add(tag)

        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, {"q": "test-search-tag"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_empty_search(self, client, admin_user):
        """Test empty search returns all snapshots."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, {"q": ""}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_no_results_search(self, client, admin_user):
        """Test search with no results."""
        client.login(username="testadmin", password="testpassword")
        url = reverse("admin:core_snapshot_changelist")
        response = client.get(url, {"q": "nonexistent-url-xyz789"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200


class TestPublicIndexSearch:
    """Tests for public index search functionality."""

    @pytest.fixture
    def public_snapshot(self, crawl, db):
        """Create sealed snapshot for public index."""
        from archivebox.core.models import Snapshot

        return Snapshot.objects.create(
            url="https://public-example.com",
            title="Public Example Website",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_by_url(self, client, public_snapshot):
        """Test public search by URL."""
        response = client.get("/public/", {"q": "public-example.com"}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_mode_selector_defaults_to_meta_for_ripgrep(self, client, monkeypatch):
        monkeypatch.setattr(SEARCH_BACKEND_CONFIG, "SEARCH_BACKEND_ENGINE", "ripgrep")

        response = client.get("/public/", HTTP_HOST=PUBLIC_HOST)

        assert response.status_code == 200
        assert b'name="search_mode" value="meta" checked' in response.content

    def test_public_search_ranks_metadata_matches_before_fulltext(self, crawl, monkeypatch):
        from archivebox.core.models import Snapshot
        from archivebox.core.views import PublicIndexView

        metadata_snapshot = Snapshot.objects.create(
            url="https://public-example.com/google-meta",
            title="Google Metadata Match",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        fulltext_snapshot = Snapshot.objects.create(
            url="https://public-example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

        monkeypatch.setattr(
            "archivebox.core.views.query_search_index",
            lambda query, search_mode=None: Snapshot.objects.filter(pk=fulltext_snapshot.pk),
        )

        request = RequestFactory().get("/public/", {"q": "google", "search_mode": "contents"})
        view = PublicIndexView()
        view.request = request

        result_ids = list(view.get_queryset().values_list("pk", flat=True))
        assert result_ids[:2] == [metadata_snapshot.pk, fulltext_snapshot.pk]

    @override_settings(PUBLIC_INDEX=True)
    def test_public_index_redirects_logged_in_users_to_admin_snapshot_list(self, client, admin_user):
        client.force_login(admin_user)

        response = client.get("/public/", HTTP_HOST=PUBLIC_HOST)

        assert response.status_code == 302
        assert response["Location"] == "/admin/core/snapshot/"

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_by_title(self, client, public_snapshot):
        """Test public search by title."""
        response = client.get("/public/", {"q": "Public Example"}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_meta(self, client, public_snapshot):
        """Test public search with query_type=meta."""
        response = client.get("/public/", {"q": "example", "query_type": "meta"}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_url(self, client, public_snapshot):
        """Test public search with query_type=url."""
        response = client.get("/public/", {"q": "public-example.com", "query_type": "url"}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_title(self, client, public_snapshot):
        """Test public search with query_type=title."""
        response = client.get("/public/", {"q": "Website", "query_type": "title"}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200
