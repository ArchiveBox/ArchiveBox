"""Stored output paths keep their legacy precedence without repeated path parsing."""

import cProfile
import pstats

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
        response = client.get("/readability/content.html", HTTP_HOST=get_snapshot_host(str(snapshot.id)))
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
