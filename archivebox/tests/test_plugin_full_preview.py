"""Plugin previews use the same registered template tags as detail cards."""

import shutil
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host


@pytest.mark.django_db
def test_chrome_full_preview_loads_plugin_ui_tags(snapshot, client):
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    captured = Path(__file__).parent / "fixtures/tlsnotary/hacker-news/navigation.json"
    output = Path(snapshot.output_dir) / "chrome/navigation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(captured, output)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="chrome/navigation.json",
        output_files={"navigation.json": {"size": output.stat().st_size, "mimetype": "application/json"}},
    )

    host = get_snapshot_host(str(snapshot.id))
    preview = client.get("/chrome/navigation.json?preview=1", HTTP_HOST=host)
    assert preview.status_code == 200
    assert b"chrome-window" in preview.content
    assert b".chrome-window .omnibox" in preview.content
    assert b"{% plugin_ui" not in preview.content
    assert b"{% load" not in preview.content

    raw = client.get("/chrome/navigation.json?raw=1", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == captured.read_bytes()
