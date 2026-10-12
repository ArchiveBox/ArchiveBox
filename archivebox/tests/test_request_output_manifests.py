"""Replay and progress reuse manifests only within one real request."""

import cProfile
import pstats

import pytest
from django.test import override_settings

from archivebox.core.routes_util import get_snapshot_host
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, WEB_TEST_HOST
from archivebox.tests.test_snapshot_output_stacks import save_output

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("preview", [False, True])
def test_replay_normalizes_manifest_once_and_reads_replaced_metadata(snapshot, client, preview):
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    result = save_output(snapshot, "readability", extra_files=tuple(f"asset-{index}.html" for index in range(64)))
    for filename in ("content.html", "replacement.html"):
        if filename == "replacement.html":
            (snapshot.output_dir / "readability" / filename).write_text("<h1>Replacement capture</h1>")
            result.output_str = filename
            result.output_files = {filename: {"size": 28, "mimetype": "text/html"}}
            result.save(update_fields=["output_str", "output_files"])
        profile = cProfile.Profile()
        with profile:
            response = client.get(
                f"/readability/{filename}",
                {"preview": "1"} if preview else {},
                HTTP_HOST=get_snapshot_host(str(snapshot.id)),
            )
            body = b"".join(response.streaming_content) if response.streaming else response.content
        assert response.status_code == 200, body
        assert "text/html" in response["Content-Type"]
        assert "Memento-Datetime" not in response  # This capture has not sealed yet.
        if preview:
            assert f"/readability/{filename}".encode() in body
        else:
            assert body == (snapshot.output_dir / "readability" / filename).read_bytes()
        normalizations = sum(
            values[1]
            for (source, _line, function), values in pstats.Stats(profile).stats.items()
            if source.endswith("core/models.py") and function == "_normalize_output_files"
        )
        assert normalizations == 1, normalizations


@pytest.mark.parametrize("metadata_only", [False, True])
def test_progress_reads_saved_manifests_without_rebuilding_them(snapshot, admin_client, metadata_only):
    Crawl.objects.filter(pk=snapshot.crawl_id).update(status=Crawl.StatusChoices.STARTED)
    results = [
        save_output(snapshot, plugin, extra_files=tuple(f"asset-{index}.html" for index in range(64)))
        for plugin in ("favicon", "screenshot")
    ]
    for filename in ("content.html", "replacement.html"):
        if filename == "replacement.html":
            for result in results:
                (snapshot.output_dir / result.plugin / filename).write_text("<h1>Replacement capture</h1>")
                result.output_str = "" if metadata_only else filename
                result.output_files = {filename: {"size": 28, "mimetype": "text/html"}}
                result.save(update_fields=["output_str", "output_files"])
        elif metadata_only:
            for result in results:
                result.output_str = ""
                result.save(update_fields=["output_str"])
        profile = cProfile.Profile()
        with profile:
            response = admin_client.get("/progress.json", {"snapshot_id": str(snapshot.id)}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        progress = response.json()["active_crawls"][0]["active_snapshots"][0]
        assert progress["id"] == str(snapshot.id)
        assert progress["completed_plugins"] == 2
        assert progress["failed_plugins"] == 0
        assert progress["favicon_url"].endswith(f"/favicon/{filename}")
        assert progress["preview_url"].endswith(f"/screenshot/{filename}")
        for result in results:
            output = next(item for item in progress["all_plugins"] if item["id"] == str(result.id))
            assert output["status"] == "succeeded"
            assert output["output_path"] == f"{result.plugin}/{filename}"
            assert output["output_url"].endswith(f"#{result.plugin}/{filename}")
        normalizations = sum(
            values[1]
            for (source, _line, function), values in pstats.Stats(profile).stats.items()
            if source.endswith("core/models.py") and function == "_normalize_output_files"
        )
        assert normalizations == 0, normalizations
        path_resolutions = sum(
            values[1]
            for (source, _line, function), values in pstats.Stats(profile).stats.items()
            if source.endswith("core/models.py") and function == "embed_path_db"
        )
        assert path_resolutions == len(results), path_resolutions


@override_settings(PUBLIC_INDEX=True)
def test_public_index_reads_saved_manifests_without_rebuilding_them(snapshot, client):
    snapshot.permissions = "public"
    snapshot.status = snapshot.StatusChoices.SEALED
    snapshot.save(update_fields=["permissions", "status"])
    results = [
        save_output(snapshot, plugin, extra_files=tuple(f"asset-{index}.html" for index in range(64)))
        for plugin in ("favicon", "screenshot", "readability")
    ]
    for filename in ("content.html", "replacement.html"):
        if filename == "replacement.html":
            for result in results:
                (snapshot.output_dir / result.plugin / filename).write_text("<h1>Replacement capture</h1>")
                result.output_str = filename
                result.output_files = {filename: {"size": 28, "mimetype": "text/html"}}
                result.save(update_fields=["output_str", "output_files"])
        profile = cProfile.Profile()
        with profile:
            response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
        assert response.status_code == 200, response.content
        body = response.content.decode()
        assert f'/favicon/{filename}" data-fallbacks=""' in body
        assert f'#readability/{filename}"' in body
        assert f"/_card/{results[1].id}" in body
        normalizations = sum(
            values[1]
            for (source, _line, function), values in pstats.Stats(profile).stats.items()
            if source.endswith("core/models.py") and function == "_normalize_output_files"
        )
        assert normalizations == 0, normalizations
