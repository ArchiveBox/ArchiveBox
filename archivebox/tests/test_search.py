import os
import re
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

import pytest
import requests
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from archivebox.machine.models import Machine
from archivebox.misc.logging import AttrDict
from archivebox.tests.conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    get_http_response,
    resolve_abxpkg_binary_env,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
)

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:8000"
WEB_HOST = "web.archivebox.localhost:8000"


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="testadmin",
        email="admin@test.com",
        password="testpassword",
    )


@pytest.fixture
def crawl(admin_user, db):
    from archivebox.crawls.models import Crawl

    return Crawl.objects.create(
        urls="https://example.com",
        created_by=admin_user,
    )


@pytest.fixture
def snapshot(crawl, db):
    from archivebox.core.models import Snapshot

    return Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


@pytest.fixture
def public_snapshot(crawl, db):
    from archivebox.core.models import Snapshot

    return Snapshot.objects.create(
        url="https://public-example.com",
        title="Public Example Website",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )


def consume_streaming_response(response):
    if response.is_async:

        async def consume():
            return b"".join([chunk async for chunk in response.streaming_content])

        return async_to_sync(consume)()
    return b"".join(response.streaming_content)


def populate_admin_search_cache(client, path, params):
    search_url = f"{path}?{urlencode(params)}"
    response = client.get(
        reverse("admin:core_snapshot_search_stream"),
        {**params, "search_url": search_url},
        HTTP_HOST=ADMIN_HOST,
    )
    assert response.status_code == 200
    assert consume_streaming_response(response)
    return client.get(path, params, HTTP_HOST=ADMIN_HOST)


def configure_ripgrep_search_backend(lib_dir: Path) -> None:
    from abx_plugins import get_plugins_dir

    binary_env = resolve_abxpkg_binary_env(
        lib_dir,
        deps_from=Path(get_plugins_dir()) / "search_backend_ripgrep" / "config.json",
    )
    rg_binary = Path(binary_env["RIPGREP_BINARY"])
    assert rg_binary.is_file()
    Machine.from_json(
        {
            "config": {
                "SEARCH_BACKEND_ENGINE": "ripgrep",
                "RIPGREP_BINARY": str(rg_binary),
            },
        },
    )


def test_search_backend_command_env_serializes_config_without_mutating_process_env(tmp_path):
    from archivebox.search.backends import search_backend_command_env

    old_env = os.environ.get("SEARCH_BACKEND_SONIC_HOST_NAME")
    os.environ["SEARCH_BACKEND_SONIC_HOST_NAME"] = "old-host"
    config = AttrDict(
        {
            "SEARCH_BACKEND_ENGINE": "sonic",
            "SEARCH_BACKEND_SONIC_HOST_NAME": "sonic",
            "SEARCH_BACKEND_SONIC_PORT": 1491,
            "SEARCH_BACKEND_SONIC_PASSWORD": "SecretPassword",
            "RIPGREP_BINARY": tmp_path / "env" / "bin" / "rg",
            "IGNORED_NONE_VALUE": None,
            "UNRELATED_BINARY_NAME": "rg",
        },
    )

    try:
        env = search_backend_command_env(config=config)
        assert env["SEARCH_BACKEND_ENGINE"] == "sonic"
        assert env["SEARCH_BACKEND_SONIC_HOST_NAME"] == "sonic"
        assert env["SEARCH_BACKEND_SONIC_PORT"] == "1491"
        assert env["SEARCH_BACKEND_SONIC_PASSWORD"] == "SecretPassword"
        assert env["RIPGREP_BINARY"] == str(tmp_path / "env" / "bin" / "rg")
        assert "IGNORED_NONE_VALUE" not in env
        assert env["UNRELATED_BINARY_NAME"] == "rg"
        assert os.environ["SEARCH_BACKEND_SONIC_HOST_NAME"] == "old-host"
    finally:
        if old_env is None:
            os.environ.pop("SEARCH_BACKEND_SONIC_HOST_NAME", None)
        else:
            os.environ["SEARCH_BACKEND_SONIC_HOST_NAME"] = old_env


def test_search_mode_options_use_canonical_backend_names():
    from archivebox.search.config import get_search_mode_options

    Machine.from_json({"config": {"SEARCH_BACKEND_ENGINE": "ripgrep"}})

    options = get_search_mode_options()

    assert {"value": "contents", "label": "deep"} in options
    assert {"value": "deep:ripgrep", "label": "deep:ripgrep"} in options
    assert all(not option["label"].startswith("deep: ") for option in options)


def test_snapshot_metadata_search_includes_notes_crawl_fields_username_and_config_values(admin_user):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.search.query import apply_snapshot_search

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=admin_user,
        label="crawl-label-needle",
        notes="crawl-notes-needle",
        config={
            "KEY_ONLY_NEEDLE": "unrelated-value",
            "SIMPLE_VALUE": "crawl-config-value-needle",
            "NESTED": {"INNER": "nested-config-value-needle"},
        },
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com/metadata-extra",
        title="Unrelated title",
        notes="snapshot-notes-needle",
        crawl=crawl,
    )

    def search_ids(query: str):
        return set(apply_snapshot_search(Snapshot.objects.all(), query, search_mode="meta").values_list("pk", flat=True))

    assert snapshot.pk in search_ids("snapshot-notes-needle")
    assert snapshot.pk in search_ids("crawl-notes-needle")
    assert snapshot.pk in search_ids("crawl-label-needle")
    assert snapshot.pk in search_ids("testadmin")
    assert snapshot.pk not in search_ids("testad")
    assert snapshot.pk not in search_ids("KEY_ONLY_NEEDLE")


class TestAdminSnapshotSearch:
    def test_admin_search_mode_selector_defaults_to_configured_deep_backend_for_ripgrep(self, client, admin_user):
        Machine.from_json({"config": {"SEARCH_BACKEND_ENGINE": "ripgrep"}})

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert response.context["cl"].search_mode == "deep:ripgrep"
        assert b'name="search_mode"' in response.content
        assert b'<option value="contents">deep</option>' in response.content
        assert b">contents<" not in response.content
        assert b'value="deep:ripgrep"' in response.content
        assert b">deep:ripgrep<" in response.content

    def test_admin_search_mode_selector_defaults_to_configured_deep_backend_for_sqlite(self, client, admin_user):
        Machine.from_json({"config": {"SEARCH_BACKEND_ENGINE": "sqlite"}})

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert response.context["cl"].search_mode == "deep:sqlite"

    def test_admin_search_mode_selector_stays_checked_after_search(self, client, admin_user, crawl):
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "contents"},
            HTTP_HOST=ADMIN_HOST,
        )

        assert response.status_code == 200
        assert response.context["cl"].search_mode == "contents"
        assert b'id="changelist"' in response.content
        assert b"search-mode-contents" in response.content

    def test_admin_search_stream_uses_real_ripgrep_backend_for_deep_results(
        self,
        client,
        admin_user,
        crawl,
        cached_abxpkg_lib_dir,
    ):
        from archivebox.core.models import Snapshot

        configure_ripgrep_search_backend(cached_abxpkg_lib_dir)
        fulltext_snapshot = Snapshot.objects.create(
            url="https://example.com/fulltext-only",
            title="Unrelated Title",
            crawl=crawl,
        )
        output_file = fulltext_snapshot.output_dir / "dom" / "output.html"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("<html><body>needle-deep-result</body></html>", encoding="utf-8")

        client.login(username="testadmin", password="testpassword")
        response = populate_admin_search_cache(
            client,
            reverse("admin:core_snapshot_changelist"),
            {"q": "needle-deep-result", "search_mode": "deep"},
        )

        assert response.status_code == 200
        assert response.context["cl"].search_mode.startswith("deep")
        assert b"search-mode-deep" in response.content
        assert str(fulltext_snapshot.id).encode() in response.content

    def test_admin_meta_search_streams_results_in_metadata_wave_order(self, client, admin_user, crawl):
        from archivebox.core.models import Snapshot

        prefix_snapshot = Snapshot.objects.create(
            url="https://google.example.com/prefix",
            title="Later Title",
            timestamp="2000000000",
            crawl=crawl,
        )
        contains_snapshot = Snapshot.objects.create(
            url="https://example.com/path/google-contained",
            title="Later Title",
            timestamp="3000000000",
            crawl=crawl,
        )
        title_snapshot = Snapshot.objects.create(
            url="https://example.com/title-only",
            title="Google Title Match",
            timestamp="1000000000",
            crawl=crawl,
        )

        client.login(username="testadmin", password="testpassword")
        path = reverse("admin:core_snapshot_changelist")
        params = {"q": "google", "search_mode": "meta"}
        response = populate_admin_search_cache(client, path, params)

        assert response.status_code == 200
        result_ids = list(response.context["cl"].queryset.values_list("pk", flat=True))
        assert result_ids[:3] == [prefix_snapshot.pk, title_snapshot.pk, contains_snapshot.pk]
        assert {title_snapshot.pk, contains_snapshot.pk, prefix_snapshot.pk}.issubset(result_ids)

    def test_admin_contents_search_stream_uses_real_backend_results(
        self,
        client,
        admin_user,
        crawl,
        cached_abxpkg_lib_dir,
    ):
        from archivebox.core.models import Snapshot

        configure_ripgrep_search_backend(cached_abxpkg_lib_dir)
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
        output_file = fulltext_snapshot.output_dir / "dom" / "output.html"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("<html><body>google fulltext match</body></html>", encoding="utf-8")

        client.login(username="testadmin", password="testpassword")
        response = populate_admin_search_cache(
            client,
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "contents"},
        )

        assert response.status_code == 200
        result_ids = list(response.context["cl"].queryset.values_list("pk", flat=True))
        assert metadata_snapshot.pk not in result_ids
        assert result_ids[:1] == [fulltext_snapshot.pk]

    def test_manual_admin_sort_applies_to_cached_search_results(self, client, admin_user, crawl):
        from archivebox.core.models import Snapshot

        older_snapshot = Snapshot.objects.create(
            url="https://example.com/google-older",
            title="A Google Older",
            timestamp="1000000000",
            crawl=crawl,
        )
        newer_snapshot = Snapshot.objects.create(
            url="https://example.com/google-newer",
            title="Z Google Newer",
            timestamp="2000000000",
            crawl=crawl,
        )

        client.login(username="testadmin", password="testpassword")
        response = populate_admin_search_cache(
            client,
            reverse("admin:core_snapshot_changelist"),
            {"q": "google", "search_mode": "meta", "o": "4"},
        )

        assert response.status_code == 200
        result_ids = list(response.context["cl"].queryset.values_list("pk", flat=True))
        assert result_ids[:2] == [older_snapshot.pk, newer_snapshot.pk]

    def test_search_by_url(self, client, admin_user, snapshot):
        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": "example.com"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b"example.com" in response.content

    def test_search_by_title(self, client, admin_user, crawl, db):
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://example.com/titled",
            title="Unique Title For Testing",
            crawl=crawl,
        )

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": "Unique Title"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_search_by_tag(self, client, admin_user, snapshot, db):
        from archivebox.core.models import Tag

        tag = Tag.objects.create(name="test-search-tag")
        snapshot.tags.add(tag)

        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": "test-search-tag"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_empty_search(self, client, admin_user):
        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": ""}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_no_results_search(self, client, admin_user):
        client.login(username="testadmin", password="testpassword")
        response = client.get(reverse("admin:core_snapshot_changelist"), {"q": "nonexistent-url-xyz789"}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200


class TestPublicIndexSearch:
    @pytest.fixture(autouse=True)
    def public_index_enabled(self):
        Machine.from_json({"config": {"PUBLIC_INDEX": True}})

    def test_public_search_by_url(self, client, public_snapshot):
        cache.clear()
        response = client.get("/public/", {"q": "public-example.com"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert b"matching snapshots..." in response.content
        assert b"No snapshots found." not in response.content

    def test_public_search_mode_selector_defaults_to_configured_deep_backend_for_ripgrep(self, client):
        Machine.from_json({"config": {"SEARCH_BACKEND_ENGINE": "ripgrep"}})

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert response.context["search_mode"] == "deep:ripgrep"
        assert b'name="search_mode"' in response.content
        assert b'<option value="contents">deep</option>' in response.content
        assert b">contents<" not in response.content
        assert b'value="deep:ripgrep"' in response.content
        assert b">deep:ripgrep<" in response.content

    def test_public_search_uses_streamed_metadata_order(
        self,
        client,
        crawl,
        cached_abxpkg_lib_dir,
    ):
        from archivebox.core.models import Snapshot

        configure_ripgrep_search_backend(cached_abxpkg_lib_dir)
        metadata_snapshot = Snapshot.objects.create(
            url="https://public-example.com/google-meta",
            title="Google Metadata Match",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        fulltext_snapshot = Snapshot.objects.create(
            url="https://public-example.com/google-url-only",
            title="Unrelated Title",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        output_file = fulltext_snapshot.output_dir / "dom" / "output.html"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("<html><body>google public fulltext match</body></html>", encoding="utf-8")

        search_params = {"q": "google", "search_mode": "meta"}
        search_url = f"/public/?{urlencode(search_params)}"
        stream_response = client.get(
            "/public/search-stream/",
            {**search_params, "search_url": search_url},
            HTTP_HOST=WEB_HOST,
        )
        assert stream_response.status_code == 200
        assert consume_streaming_response(stream_response)

        response = client.get("/public/", search_params, HTTP_HOST=WEB_HOST)

        content = response.content.decode()
        assert content.index(str(metadata_snapshot.url)) < content.index(str(fulltext_snapshot.url))

    def test_public_metadata_search_prioritizes_common_url_prefixes(self, client, crawl):
        from archivebox.core.models import Snapshot

        broad_match = Snapshot.objects.create(
            url="https://late.example.com/path/to/iana",
            title="Unrelated Broad Match",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )
        prefix_match = Snapshot.objects.create(
            url="https://www.iana.org/domains/reserved",
            title="Unrelated Prefix Match",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

        search_params = {"q": "iana", "search_mode": "meta"}
        search_url = f"/public/?{urlencode(search_params)}"
        stream_response = client.get(
            "/public/search-stream/",
            {**search_params, "search_url": search_url},
            HTTP_HOST=WEB_HOST,
        )
        assert stream_response.status_code == 200
        assert consume_streaming_response(stream_response)

        response = client.get("/public/", search_params, HTTP_HOST=WEB_HOST)
        content = response.content.decode()

        assert content.index(str(prefix_match.url)) < content.index(str(broad_match.url))

    def test_public_search_by_title(self, client, public_snapshot):
        response = client.get("/public/", {"q": "Public Example"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert b"archivebox-search-stream-status" in response.content

    def test_public_search_stream_preserves_search_form_dom(self, client, public_snapshot):
        response = client.get("/public/", {"q": "Public Example"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert b"replaceRegionFromDocument(doc, '.public-snapshot-count')" in response.content
        assert b"replaceRegionFromDocument(doc, '#table-bookmarks tbody')" in response.content
        assert b"currentList.replaceWith(nextList)" not in response.content

    def test_public_search_stream_populates_public_results_cache(self, client, public_snapshot):
        search_params = {"q": "Public Example", "search_mode": "meta"}
        search_url = f"/public/?{urlencode(search_params)}"

        response = client.get(
            "/public/search-stream/",
            {**search_params, "search_url": search_url},
            HTTP_HOST=WEB_HOST,
        )

        assert response.status_code == 200
        assert response["X-Accel-Buffering"] == "no"
        assert consume_streaming_response(response)

        response = client.get("/public/", search_params, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert b"Public Example Website" in response.content
        assert b"No snapshots found." not in response.content

    def test_public_index_shows_exact_total_count_and_page_count_for_100_plus_snapshots(self, client, crawl, public_snapshot):
        from archivebox.core.models import Snapshot

        base_time = public_snapshot.bookmarked_at + timedelta(seconds=1)

        Snapshot.objects.bulk_create(
            [
                Snapshot(
                    url=f"https://public-page-test-{index:03d}.example.com",
                    title=f"Public Page Test {index:03d}",
                    crawl=crawl,
                    status=Snapshot.StatusChoices.SEALED,
                    config={"PERMISSIONS": "public"},
                    created_at=base_time + timedelta(seconds=index),
                    bookmarked_at=base_time + timedelta(seconds=index),
                    timestamp=str((base_time + timedelta(seconds=index)).timestamp()),
                )
                for index in range(124)
            ]
            + [
                Snapshot(
                    url=f"https://private-page-test-{index:03d}.example.com",
                    title=f"Private Page Test {index:03d}",
                    crawl=crawl,
                    status=Snapshot.StatusChoices.SEALED,
                    config={"PERMISSIONS": "private"},
                    created_at=base_time + timedelta(seconds=124 + index),
                    bookmarked_at=base_time + timedelta(seconds=124 + index),
                    timestamp=str((base_time + timedelta(seconds=124 + index)).timestamp()),
                )
                for index in range(5)
            ],
        )

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        assert response.context["paginator"].count == 125
        assert response.context["paginator"].num_pages == 3
        assert response.context["page_obj"].has_next() is True
        assert len(response.context["object_list"]) == 50
        content = response.content.decode()
        assert "1-50 of 125" in content
        assert "page 1 of 3" in content
        assert "Snapshot (125)" in content
        assert "last &raquo;" in content
        assert "private-page-test" not in content

        last_response = client.get("/public/", {"page": 3}, HTTP_HOST=WEB_HOST)

        assert last_response.status_code == 200
        assert last_response.context["paginator"].count == 125
        assert last_response.context["paginator"].num_pages == 3
        assert last_response.context["page_obj"].has_next() is False
        assert len(last_response.context["object_list"]) == 25
        last_content = last_response.content.decode()
        assert "101-125 of 125" in last_content
        assert "Page 3 of 3" in last_content
        assert "last &raquo;" not in last_content
        assert "private-page-test" not in last_content

    def test_public_index_preview_respects_root_relative_screenshot_output(self, client, public_snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=public_snapshot,
            plugin="screenshot",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={
                "screenshot.png": {"size": 3, "root_relative": True},
            },
            output_str="screenshot.png",
        )

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        assert "/screenshot.png" in content
        assert "/screenshot/screenshot.png" not in content

    def test_public_index_preview_respects_plugin_relative_screenshot_output(self, client, public_snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=public_snapshot,
            plugin="screenshot",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={
                "screenshot.png": {"size": 3},
            },
            output_str="screenshot.png",
        )

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        assert "screenshot/screenshot.png" in content

    def test_public_index_preview_falls_back_to_extension_screenshots(self, client, public_snapshot):
        from archivebox.core.models import ArchiveResult

        ArchiveResult.objects.create(
            snapshot=public_snapshot,
            plugin="chrome_extension_screenshot",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_files={
                "screenshot-2.png": {"size": 2},
                "screenshot.png": {"size": 1},
                "screenshot-1.png": {"size": 3},
            },
        )

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        first = content.index("chrome_extension_screenshot/screenshot-1.png")
        second = content.index("chrome_extension_screenshot/screenshot.png")
        assert first < second
        assert "/screenshot/screenshot.png" not in content
        assert "chrome_extension_screenshot/screenshot-2.png" not in content

    def test_public_index_snapshot_without_preview_renders_placeholder(self, client, public_snapshot):
        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        assert "snapshot-preview-empty" in content
        assert "screenshot/screenshot.png" not in content

    def test_public_index_pending_snapshot_uses_small_preview_spinner(self, client, crawl):
        from archivebox.core.models import Snapshot

        Snapshot.objects.create(
            url="https://pending-public-example.com",
            title="Pending Public Example",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
        )

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        assert "snapshot-preview-spinner" in content
        assert "spinner.gif" in content

    def test_public_index_finished_snapshot_without_title_falls_back_to_url(self, client, public_snapshot):
        public_snapshot.title = ""
        public_snapshot.save(update_fields=["title"])

        response = client.get("/public/", HTTP_HOST=WEB_HOST)

        assert response.status_code == 200
        content = response.content.decode()
        assert "https://public-example.com" in content
        assert "Loading..." not in content

    def test_public_search_query_type_meta(self, client, public_snapshot):
        response = client.get("/public/", {"q": "example", "query_type": "meta"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200

    def test_public_search_query_type_url(self, client, public_snapshot):
        response = client.get("/public/", {"q": "public-example.com", "query_type": "url"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200

    def test_public_search_query_type_title(self, client, public_snapshot):
        response = client.get("/public/", {"q": "Website", "query_type": "title"}, HTTP_HOST=WEB_HOST)

        assert response.status_code == 200


class TestSearchBackendsE2E:
    @pytest.mark.timeout(360)
    def test_live_public_and_admin_search_matrix_uses_real_cli_indexing_and_streaming(self, initialized_archive):
        from abx_plugins import get_plugins_dir

        plugins_dir = Path(get_plugins_dir())
        lib_dir = initialized_archive / "lib"
        install_result = run_archivebox_cmd(
            ["install", "wget", "search_backend_ripgrep", "search_backend_sonic"],
            cwd=initialized_archive,
            env={"ABXPKG_LIB_DIR": str(lib_dir)},
            default_cli_env=True,
        )
        assert install_result.returncode == 0, install_result.stderr or install_result.stdout
        binary_env = resolve_abxpkg_binary_env(
            lib_dir,
            deps_from=[
                plugins_dir / "wget" / "config.json",
                plugins_dir / "search_backend_ripgrep" / "config.json",
                plugins_dir / "search_backend_sonic" / "config.json",
            ],
        )
        assert Path(binary_env["RIPGREP_BINARY"]).is_file()
        assert Path(binary_env["SONIC_BINARY"]).is_file()

        page_count = 23
        first_batch_count = 12
        total_snapshot_count = page_count + 7
        url_only_path = "/urlonlymetaprecisionunique.html"
        title_only_path = "/title-only.html"
        tag_only_path = "/tag-only.html"
        title_prefix_order_path = "/title-prefix-order.html"
        url_contains_order_path = "/url-orderneedle.html"
        title_contains_order_path = "/title-contains-order.html"
        tag_order_path = "/tag-order.html"
        url_only_needle = "urlonlymetaprecisionunique"
        title_only_needle = "livematrixtitleprecisionunique"
        tag_only_needle = "livematrixtagprecisionunique"
        order_needle = "orderneedle"
        first_batch_content_needle = "firstbatchcontentonlyneedle"
        second_batch_content_needle = "secondbatchcontentonlyneedle"
        shared_content_needle = "sharedcontentneedle"
        overlapping_content_needle = "overlappingcontentneedle"
        title_prefix_order_title = "Orderneedle Title Prefix Page"
        title_contains_order_title = "Contains Orderneedle Later Page"
        pages = {
            f"/page-{index:03d}.html": (
                "<!doctype html><html><head>"
                f"<title>Search Matrix Page {index:03d}</title>"
                "</head><body>"
                f"archivebox-ui-stream-needle page-{index:03d} "
                "real wget output for public admin search matrix "
                f"{shared_content_needle} "
                f"{first_batch_content_needle if index < first_batch_count else second_batch_content_needle} "
                f"{overlapping_content_needle if index in (0, 1, 2, first_batch_count, first_batch_count + 1) else ''}"
                "</body></html>"
            ).encode()
            for index in range(page_count)
        }
        pages.update(
            {
                url_only_path: (
                    b"<!doctype html><html><head><title>URL Only Precision Page</title></head>"
                    b"<body>body text intentionally avoids the other precision needles</body></html>"
                ),
                title_only_path: (
                    f"<!doctype html><html><head><title>{title_only_needle}</title></head>"
                    "<body>body text intentionally avoids the title precision needle</body></html>"
                ).encode(),
                tag_only_path: (
                    b"<!doctype html><html><head><title>Tag Only Precision Page</title></head>"
                    b"<body>body text intentionally avoids the tag precision needle</body></html>"
                ),
                title_prefix_order_path: (
                    f"<!doctype html><html><head><title>{title_prefix_order_title}</title></head>"
                    "<body>body text intentionally avoids the ordering precision needle</body></html>"
                ).encode(),
                url_contains_order_path: (
                    b"<!doctype html><html><head><title>URL Contains Ordering Page</title></head>"
                    b"<body>body text intentionally avoids the ordering precision needle</body></html>"
                ),
                title_contains_order_path: (
                    f"<!doctype html><html><head><title>{title_contains_order_title}</title></head>"
                    "<body>body text intentionally avoids the ordering precision needle</body></html>"
                ).encode(),
                tag_order_path: (
                    b"<!doctype html><html><head><title>Tag Ordering Page</title></head>"
                    b"<body>body text intentionally avoids the ordering precision needle</body></html>"
                ),
            },
        )

        class SearchMatrixHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = pages.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, _format, *args):
                pass

        fixture_server = ThreadingHTTPServer(("127.0.0.1", 0), SearchMatrixHandler)
        fixture_thread = Thread(target=fixture_server.serve_forever, daemon=True)
        fixture_thread.start()

        archivebox_server = None
        try:
            fixture_port = fixture_server.server_address[1]
            matrix_urls = [f"http://127.0.0.1:{fixture_port}/page-{index:03d}.html" for index in range(page_count)]
            url_only_url = f"http://127.0.0.1:{fixture_port}{url_only_path}"
            title_only_url = f"http://127.0.0.1:{fixture_port}{title_only_path}"
            tag_only_url = f"http://127.0.0.1:{fixture_port}{tag_only_path}"
            title_prefix_order_url = f"http://127.0.0.1:{fixture_port}{title_prefix_order_path}"
            url_contains_order_url = f"http://127.0.0.1:{fixture_port}{url_contains_order_path}"
            title_contains_order_url = f"http://127.0.0.1:{fixture_port}{title_contains_order_path}"
            tag_order_url = f"http://127.0.0.1:{fixture_port}{tag_order_path}"
            urls = [
                *matrix_urls,
                url_only_url,
                title_only_url,
                tag_only_url,
                title_prefix_order_url,
                url_contains_order_url,
                title_contains_order_url,
                tag_order_url,
            ]
            archivebox_port = get_free_port()
            sonic_port = get_free_port()
            env = cli_env(
                live=True,
                ABXPKG_LIB_DIR=str(lib_dir),
                PLUGINS="wget,search_backend_ripgrep,search_backend_sqlite,search_backend_sonic",
                SAVE_TITLE="True",
                WGET_ENABLED="True",
                TIMEOUT="20",
                PUBLIC_INDEX="True",
                PUBLIC_ADD_VIEW="True",
                PERMISSIONS="public",
                URL_ALLOWLIST=rf"127\.0\.0\.1:{fixture_port}/.*",
                URL_DENYLIST="",
                ALLOWED_HOSTS="*",
                BASE_URL=f"http://archivebox.localhost:{archivebox_port}",
                SEARCH_BACKEND_ENGINE="sonic",
                SEARCH_BACKEND_RIPGREP_ENABLED="True",
                SEARCH_BACKEND_SQLITE_ENABLED="True",
                SEARCH_BACKEND_SONIC_ENABLED="True",
                SEARCH_BACKEND_SONIC_PORT=str(sonic_port),
            )
            env.update(binary_env)
            create_admin_and_token(initialized_archive)

            wget_capture_urls = [*matrix_urls]
            first_wget_urls = wget_capture_urls[:first_batch_count]
            second_wget_urls = wget_capture_urls[first_batch_count:]
            first_add_result = run_archivebox_cmd(
                [
                    "add",
                    "--depth=0",
                    f"--max-urls={len(first_wget_urls)}",
                    "--crawl-max-concurrent-snapshots=4",
                    "--parser=url_list",
                    "--plugins=wget",
                    "--tag=search-matrix",
                    *first_wget_urls,
                ],
                cwd=initialized_archive,
                env={
                    **env,
                    "SEARCH_BACKEND_SONIC_ENABLED": "False",
                    "SEARCH_BACKEND_SQLITE_ENABLED": "False",
                },
                timeout=120,
            )
            assert first_add_result.returncode == 0, first_add_result.stderr or first_add_result.stdout

            second_add_result = run_archivebox_cmd(
                [
                    "add",
                    "--depth=0",
                    f"--max-urls={len(second_wget_urls)}",
                    "--crawl-max-concurrent-snapshots=4",
                    "--parser=url_list",
                    "--plugins=wget",
                    "--tag=search-matrix",
                    *second_wget_urls,
                ],
                cwd=initialized_archive,
                env=env,
                timeout=120,
            )
            assert second_add_result.returncode == 0, second_add_result.stderr or second_add_result.stdout

            metadata_snapshots = [
                (url_only_url, "URL Only Precision Page", "search-matrix"),
                (title_only_url, title_only_needle, "search-matrix"),
                (tag_only_url, "Tag Only Precision Page", f"search-matrix,{tag_only_needle}"),
                (title_prefix_order_url, title_prefix_order_title, "search-matrix"),
                (url_contains_order_url, "URL Contains Ordering Page", "search-matrix"),
                (title_contains_order_url, title_contains_order_title, "search-matrix"),
                (tag_order_url, "Tag Ordering Page", f"search-matrix,{order_needle}"),
            ]
            metadata_create_outputs = []
            for url, _title, tags in metadata_snapshots:
                create_result = run_archivebox_cmd(
                    ["snapshot", "create", f"--tag={tags}", url],
                    cwd=initialized_archive,
                    env=env,
                    timeout=60,
                )
                assert create_result.returncode == 0, create_result.stderr or create_result.stdout
                metadata_create_outputs.append(create_result.stdout)
            from archivebox.core.models import Snapshot
            from archivebox.tests.test_orm_helpers import use_archivebox_db

            with use_archivebox_db(initialized_archive):
                for url, title, _tags in metadata_snapshots:
                    Snapshot.objects.filter(url=url).update(title=title)
            metadata_seal_result = run_archivebox_cmd(
                ["snapshot", "update", "--status=sealed"],
                cwd=initialized_archive,
                env=env,
                input="".join(metadata_create_outputs),
                timeout=60,
            )
            assert metadata_seal_result.returncode == 0, metadata_seal_result.stderr or metadata_seal_result.stdout

            list_result = run_archivebox_cmd(
                ["list", "--url__icontains", f"127.0.0.1:{fixture_port}", "--csv=url"],
                cwd=initialized_archive,
                env=env,
                timeout=60,
            )
            assert list_result.returncode == 0, list_result.stderr or list_result.stdout
            listed_urls = [line.strip().strip('"') for line in list_result.stdout.splitlines() if line.strip()]
            assert len(urls) == total_snapshot_count
            assert set(listed_urls) == set(urls)

            index_update = run_archivebox_cmd(
                ["update", "--index-only", "--batch-size=10"],
                cwd=initialized_archive,
                env=env,
                timeout=180,
            )
            assert index_update.returncode == 0, index_update.stderr or index_update.stdout

            cli_backend_expectations = (
                ("ripgrep", shared_content_needle, matrix_urls),
                ("sqlite", first_batch_content_needle, first_wget_urls),
                ("sonic", overlapping_content_needle, [*first_wget_urls[:3], *second_wget_urls[:2]]),
                ("sonic", tag_only_needle, [tag_only_url]),
            )
            for backend_name, query, expected_urls in cli_backend_expectations:
                backend_result = run_archivebox_cmd(
                    ["list", "--search=contents", "--csv=url", query],
                    cwd=initialized_archive,
                    env={**env, "SEARCH_BACKEND_ENGINE": backend_name},
                    timeout=60,
                )
                assert backend_result.returncode == 0, backend_result.stderr or backend_result.stdout
                backend_urls = [line.strip().strip('"') for line in backend_result.stdout.splitlines() if line.strip()]
                assert set(backend_urls) == set(expected_urls), (backend_name, query, backend_result.stdout)

            archivebox_server = start_archivebox_server(
                initialized_archive,
                port=archivebox_port,
                log_name="search-matrix-server.log",
                env=env,
            )
            get_http_response(
                archivebox_port,
                host=f"web.archivebox.localhost:{archivebox_port}",
                path="/public/",
                process=archivebox_server,
            )
            get_http_response(
                archivebox_port,
                host=f"admin.archivebox.localhost:{archivebox_port}",
                path="/admin/login/",
                process=archivebox_server,
            )

            session = requests.Session()
            login_page = session.get(
                f"http://127.0.0.1:{archivebox_port}/admin/login/",
                headers={"Host": f"admin.archivebox.localhost:{archivebox_port}"},
                timeout=10,
            )
            assert login_page.status_code == 200
            csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
            assert csrf_match, login_page.text[:500]
            login_response = session.post(
                f"http://127.0.0.1:{archivebox_port}/admin/login/",
                headers={
                    "Host": f"admin.archivebox.localhost:{archivebox_port}",
                    "Referer": f"http://admin.archivebox.localhost:{archivebox_port}/admin/login/",
                },
                data={
                    "username": "apitestadmin",
                    "password": "testpass123",
                    "csrfmiddlewaretoken": csrf_match.group(1),
                    "next": "/admin/core/snapshot/",
                },
                timeout=10,
                allow_redirects=False,
            )
            assert login_response.status_code in (302, 303), login_response.text

            public_default = requests.get(
                f"http://127.0.0.1:{archivebox_port}/public/",
                headers={"Host": f"web.archivebox.localhost:{archivebox_port}"},
                timeout=10,
            )
            assert public_default.status_code == 200
            assert "archivebox-search-stream-status" in public_default.text
            assert 'value="deep:sonic" selected' in public_default.text
            assert "No snapshots found." not in public_default.text
            assert "127.0.0.1" in public_default.text

            admin_default = session.get(
                f"http://127.0.0.1:{archivebox_port}/admin/core/snapshot/",
                headers={"Host": f"admin.archivebox.localhost:{archivebox_port}"},
                timeout=10,
            )
            assert admin_default.status_code == 200
            assert "archivebox-search-stream-status" in admin_default.text
            assert 'value="deep:sonic" selected' in admin_default.text
            assert "127.0.0.1" in admin_default.text

            for surface_name, host, stream_path, list_path, requester in (
                (
                    "public",
                    f"web.archivebox.localhost:{archivebox_port}",
                    "/public/search-stream/",
                    "/public/",
                    requests,
                ),
                (
                    "admin",
                    f"admin.archivebox.localhost:{archivebox_port}",
                    "/admin/core/snapshot/search-stream/",
                    "/admin/core/snapshot/",
                    session,
                ),
            ):
                for search_mode, query, expected_urls in (
                    ("meta", "search-matrix", urls),
                    ("deep:ripgrep", first_batch_content_needle, first_wget_urls),
                    ("deep:ripgrep", second_batch_content_needle, second_wget_urls),
                    ("deep:ripgrep", shared_content_needle, matrix_urls),
                    ("deep:ripgrep", overlapping_content_needle, [*first_wget_urls[:3], *second_wget_urls[:2]]),
                    ("deep:sqlite", first_batch_content_needle, first_wget_urls),
                    ("deep:sqlite", second_batch_content_needle, second_wget_urls),
                    ("deep:sqlite", shared_content_needle, matrix_urls),
                    ("deep:sqlite", overlapping_content_needle, [*first_wget_urls[:3], *second_wget_urls[:2]]),
                    ("deep:sonic", first_batch_content_needle, first_wget_urls),
                    ("deep:sonic", second_batch_content_needle, second_wget_urls),
                    ("deep:sonic", shared_content_needle, matrix_urls),
                    ("deep:sonic", overlapping_content_needle, [*first_wget_urls[:3], *second_wget_urls[:2]]),
                    ("deep:sonic", url_only_needle, [url_only_url]),
                    ("deep:sonic", title_only_needle, [title_only_url]),
                    ("deep:sonic", tag_only_needle, [tag_only_url]),
                ):
                    params = {"q": query, "search_mode": search_mode}
                    search_url = f"{list_path}?{urlencode(params)}"
                    expected_count = len(expected_urls)
                    partial_count = min(10, expected_count)

                    initial_page_started = time.monotonic()
                    initial_page = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{list_path}",
                        headers={"Host": host},
                        params=params,
                        timeout=10,
                    )
                    initial_page_elapsed = time.monotonic() - initial_page_started
                    assert initial_page.status_code == 200
                    assert "archivebox-search-stream-status" in initial_page.text
                    assert query in initial_page.text
                    assert f'value="{search_mode}" selected' in initial_page.text
                    assert initial_page_elapsed < 1.0, (surface_name, search_mode, initial_page_elapsed)

                    stream_started = time.monotonic()
                    stream_response = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{stream_path}",
                        headers={"Host": host},
                        params={**params, "search_url": search_url},
                        stream=True,
                        timeout=(5, 30),
                    )
                    assert stream_response.status_code == 200, stream_response.text[:500]
                    assert stream_response.headers.get("X-Accel-Buffering") == "no"

                    counts = []
                    count_events = []
                    first_positive_elapsed = None
                    first_partial_page_checked = False
                    later_partial_page_checked = False
                    for line in stream_response.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        now = time.monotonic()
                        count = int(line.strip())
                        counts.append(count)
                        count_events.append((count, now - stream_started))
                        if count > 0 and first_positive_elapsed is None:
                            first_positive_elapsed = now - stream_started

                        if count > 0 and not first_partial_page_checked:
                            first_partial_page_checked = True
                            partial_page_started = time.monotonic()
                            partial_page = requester.get(
                                f"http://127.0.0.1:{archivebox_port}{list_path}",
                                headers={"Host": host},
                                params=params,
                                timeout=10,
                            )
                            partial_page_elapsed = time.monotonic() - partial_page_started
                            assert partial_page.status_code == 200
                            assert "No snapshots found." not in partial_page.text
                            assert "127.0.0.1" in partial_page.text
                            assert partial_page_elapsed < 1.0, (surface_name, search_mode, count, partial_page_elapsed)

                        if count >= partial_count and not later_partial_page_checked:
                            later_partial_page_checked = True
                            partial_page = requester.get(
                                f"http://127.0.0.1:{archivebox_port}{list_path}",
                                headers={"Host": host},
                                params=params,
                                timeout=10,
                            )
                            assert partial_page.status_code == 200
                            assert "No snapshots found." not in partial_page.text
                            assert "127.0.0.1" in partial_page.text

                    total_elapsed = time.monotonic() - stream_started
                    assert counts[0] == 0, (surface_name, search_mode, counts[:10])
                    assert counts[1] == 1, (surface_name, search_mode, counts[:10])
                    assert counts[-1] == expected_count, (surface_name, search_mode, counts[-10:])
                    assert counts == sorted(counts), (surface_name, search_mode, counts[:20])
                    assert first_partial_page_checked
                    assert later_partial_page_checked
                    positive_events = [(count, elapsed) for count, elapsed in count_events if count > 0]
                    # Fast backends can stream the only positive match in one event; when
                    # there are multiple positive events, still verify progress stays live.
                    if len(positive_events) > 1:
                        max_progress_gap = max(
                            later_elapsed - earlier_elapsed for (_, earlier_elapsed), (_, later_elapsed) in pairwise(positive_events)
                        )
                        assert max_progress_gap < 1.0, (surface_name, search_mode, max_progress_gap, positive_events[:10])
                    assert first_positive_elapsed is not None and first_positive_elapsed < 0.75, (
                        surface_name,
                        search_mode,
                        first_positive_elapsed,
                        counts[:10],
                    )
                    assert total_elapsed < 2.0, (surface_name, search_mode, total_elapsed, counts[-10:])

                    rendered_page = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{list_path}",
                        headers={"Host": host},
                        params=params,
                        timeout=10,
                    )
                    assert rendered_page.status_code == 200
                    assert "No snapshots found." not in rendered_page.text
                    assert any(expected_url in rendered_page.text for expected_url in expected_urls)
                    assert search_mode in rendered_page.text

                    cleared_page = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{list_path}",
                        headers={"Host": host},
                        timeout=10,
                    )
                    assert cleared_page.status_code == 200
                    assert "No snapshots found." not in cleared_page.text
                    assert "127.0.0.1" in cleared_page.text

                for query, expected_url, absent_urls in (
                    (url_only_needle, url_only_url, (title_only_url, tag_only_url)),
                    (title_only_needle, title_only_url, (url_only_url, tag_only_url)),
                    (tag_only_needle, tag_only_url, (url_only_url, title_only_url)),
                ):
                    params = {"q": query, "search_mode": "meta"}
                    search_url = f"{list_path}?{urlencode(params)}"
                    stream_response = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{stream_path}",
                        headers={"Host": host},
                        params={**params, "search_url": search_url},
                        stream=True,
                        timeout=(5, 30),
                    )
                    assert stream_response.status_code == 200, stream_response.text[:500]
                    counts = [int(line.strip()) for line in stream_response.iter_lines(decode_unicode=True) if line]
                    assert counts[-1] == 1, (surface_name, query, counts)

                    rendered_page = requester.get(
                        f"http://127.0.0.1:{archivebox_port}{list_path}",
                        headers={"Host": host},
                        params=params,
                        timeout=10,
                    )
                    assert rendered_page.status_code == 200
                    assert expected_url in rendered_page.text
                    for absent_url in absent_urls:
                        assert absent_url not in rendered_page.text

                params = {"q": order_needle, "search_mode": "meta"}
                search_url = f"{list_path}?{urlencode(params)}"
                stream_response = requester.get(
                    f"http://127.0.0.1:{archivebox_port}{stream_path}",
                    headers={"Host": host},
                    params={**params, "search_url": search_url},
                    stream=True,
                    timeout=(5, 30),
                )
                assert stream_response.status_code == 200, stream_response.text[:500]
                counts = [int(line.strip()) for line in stream_response.iter_lines(decode_unicode=True) if line]
                assert counts[-1] == 4, (surface_name, order_needle, counts)

                rendered_page = requester.get(
                    f"http://127.0.0.1:{archivebox_port}{list_path}",
                    headers={"Host": host},
                    params=params,
                    timeout=10,
                )
                assert rendered_page.status_code == 200
                rendered_text = rendered_page.text
                assert rendered_text.index(title_prefix_order_url) < rendered_text.index(url_contains_order_url)
                assert rendered_text.index(url_contains_order_url) < rendered_text.index(title_contains_order_url)
                assert rendered_text.index(title_contains_order_url) < rendered_text.index(tag_order_url)
        finally:
            if archivebox_server is not None:
                stop_archivebox_process(archivebox_server)
            fixture_server.shutdown()
            fixture_server.server_close()
            fixture_thread.join(timeout=5)
