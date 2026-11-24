"""Stored output paths keep their legacy precedence without repeated path parsing."""

import cProfile
import json
import pstats
from urllib.parse import quote

import pytest

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host
from archivebox.tests.test_snapshot_output_stacks import save_output

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("requested", "files", "expected"),
    [
        ("capture.html", {"capture.html": {}}, "wget/capture.html"),
        ("wget/capture.html", {"capture.html": {}}, "wget/capture.html"),
        ("capture.html", {"wget/capture.html": {}}, "wget/capture.html"),
        ("wget/capture.html", {"wget/capture.html": {}}, "wget/capture.html"),
        ("capture.html", {"capture.html": {"root_relative": True}}, "capture.html"),
        ("wget/capture.html", {"wget/capture.html": {"root_relative": True}}, "capture.html"),
        ("capture.html", {"capture.html": {"root_relative": True}, "wget/capture.html": {}}, "capture.html"),
        ("wget/capture.html", {"capture.html": {"root_relative": True}, "wget/capture.html": {}}, "wget/capture.html"),
        ("sub/space & café%20.html", {"sub/space & café%20.html": {}}, "wget/sub/space & café%20.html"),
        ("../capture.html", {"capture.html": {}}, None),
        ("wget/./../capture.html", {"capture.html": {}}, None),
        ("wget//../capture.html", {"capture.html": {}}, None),
        ("/capture.html", {"capture.html": {}}, None),
        ("missing.html", {"capture.html": {}}, None),
        ("", {"capture.html": {}}, None),
    ],
)
def test_saved_output_path_resolution(snapshot, requested, files, expected):
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="wget", status="succeeded", output_files=files)
    assert result.output_file_path(requested) == expected


def test_replay_resolves_manifest_paths_without_constructing_path_objects(snapshot, client):
    snapshot.config = {"PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    save_output(snapshot, "readability")
    profile = cProfile.Profile()
    with profile:
        response = client.get("/readability/content.html", {"raw": "1"}, HTTP_HOST=get_snapshot_host(str(snapshot.id)))
        body = b"".join(response.streaming_content) if response.streaming else response.content
    assert response.status_code == 200
    assert body == (snapshot.output_dir / "readability/content.html").read_bytes()
    path_calls = sum(
        calls[0]
        for (source, _line, _function), values in pstats.Stats(profile).stats.items()
        if "pathlib" in source
        for (_caller_source, _caller_line, caller), calls in values[4].items()
        if caller == "_resolve_output_file_path"
    )
    assert path_calls == 0, "Manifest-relative POSIX paths should not rebuild pathlib objects"


@pytest.mark.parametrize(("explicit_primary", "preview"), [(False, False), (True, False), (True, True)])
def test_replay_reuses_normalized_large_manifest(snapshot, client, explicit_primary, preview):
    snapshot.config = {"PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / "wget/assets/page.css"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("body { color: blue; }")
    files = {f"assets/{index:05}.css": {"extension": "css", "mimetype": "text/css", "size": 12} for index in range(10001)}
    files["assets/page.css"] = {"extension": "css", "mimetype": "text/css", "size": output.stat().st_size}
    if explicit_primary:
        files["index.html"] = {"extension": "html", "mimetype": "text/html", "size": 12}
    ArchiveResult.objects.create(snapshot=snapshot, plugin="wget", status="succeeded", output_str="wget/index.html", output_files=files)
    with cProfile.Profile() as profile:
        response = client.get(
            "/wget/assets/page.css",
            {"preview": "full"} if preview else {},
            HTTP_HOST=get_snapshot_host(str(snapshot.id)),
        )
        body = b"".join(response.streaming_content) if response.streaming else response.content
    assert response.status_code == 200
    if preview:
        assert response["Content-Type"].startswith("text/html")
        assert b"<!doctype html>" in body.lower()
        assert output.read_bytes() in body
    else:
        assert body == output.read_bytes()
    normalized_files = sum(
        calls[0]
        for (_source, _line, function), values in pstats.Stats(profile).stats.items()
        if function == "model_validate"
        for (caller_source, _caller_line, caller), calls in values[4].items()
        if caller == "from_files" and caller_source.endswith("output_files.py")
    )
    assert normalized_files == 0, "Replay should not validate every stored file again to serve one asset"
    from archivebox.core.views import _resolve_archiveresult_relpath

    path, result, _fallbacks = _resolve_archiveresult_relpath(snapshot, "wget/assets/page.css", include_all_files=preview)
    assert path == "wget/assets/page.css"
    assert result is not None
    if explicit_primary and not preview:
        assert result.output_file_map() == {"index.html": files["index.html"], "assets/page.css": files["assets/page.css"]}
        assert "output_files" in result.get_deferred_fields()
        assert len(result._replay_primary_files) < 256
    else:
        assert result.output_file_map() == files


@pytest.mark.parametrize("manifest_kind", ["mapping", "paths", "records", "json", "null", "scalar"])
@pytest.mark.parametrize("filename", ["style.css", "123", 'space & café ".css', "nested/style.css"])
def test_replay_projection_preserves_legacy_manifest_paths(snapshot, client, manifest_kind, filename):
    snapshot.config = {"PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / "wget" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("body { color: blue; }")
    metadata = {"extension": "html", "mimetype": "text/html", "size": 10}
    manifests = {
        "mapping": {"index.html": metadata, filename: {"size": str(output.stat().st_size)}},
        "paths": ["index.html", filename],
        "records": [{"path": "index.html", **metadata}, {"path": filename}],
        "json": json.dumps({"index.html": metadata, filename: {}}),
        "null": {"index.html": metadata, filename: None},
        "scalar": {"index.html": metadata, filename: 10},
    }
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        status="succeeded",
        output_str="wget/index.html",
        output_files=manifests[manifest_kind],
    )
    response = client.get(f"/wget/{quote(filename)}", HTTP_HOST=get_snapshot_host(str(snapshot.id)))
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert response.status_code == 200
    assert body == output.read_bytes()
    assert "Memento-Datetime" not in response


@pytest.mark.parametrize("root_relative", [False, True])
def test_replay_projection_preserves_replacement_primary_and_root_precedence(snapshot, client, root_relative):
    from django.utils import timezone

    snapshot.config = {"PERMISSIONS": "public"}
    snapshot.downloaded_at = timezone.now()
    snapshot.save(update_fields=["config", "downloaded_at"])
    plugin_file = snapshot.output_dir / "readability/replacement.html"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_text("<html><body>Plugin replacement</body></html>")
    root_file = snapshot.output_dir / "replacement.html"
    root_file.write_text("<html><body>Legacy root replacement</body></html>")
    snapshot.output_size = plugin_file.stat().st_size + root_file.stat().st_size
    snapshot.save(update_fields=["output_size"])
    metadata = {"extension": "html", "mimetype": "text/html", "size": plugin_file.stat().st_size}
    files = {"readability/replacement.html": metadata}
    if root_relative:
        files["replacement.html"] = {**metadata, "root_relative": True}
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="readability",
        status="succeeded",
        output_str="readability/replacement.html",
        output_files=files,
    )
    response = client.get("/readability/replacement.html", {"raw": "1"}, HTTP_HOST=get_snapshot_host(str(snapshot.id)))
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert response.status_code == 200
    assert body == (root_file if root_relative else plugin_file).read_bytes()
    assert ("Memento-Datetime" in response) is not root_relative
