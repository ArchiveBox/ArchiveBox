"""Gallery billing exceptions preserve failed captures and reject other errors."""

import pytest
import json
import gzip
from pathlib import Path

from archivebox.core.models import ArchiveResult


@pytest.mark.django_db
@pytest.mark.parametrize(
    "message",
    [
        "OpenCode analysis failed: APIError: You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/",
        "OpenCode analysis failed: APIError: Your credit balance is too low to access the Anthropic API",
    ],
)
def test_gallery_warns_for_exhausted_credit_results(snapshot, capsys, message):
    from archivebox.core.library_screenshots import validate_ai_result

    tags_before = list(snapshot.tags.values_list("pk", flat=True))
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    assert validate_ai_result(snapshot, "autotag") is False
    assert "::warning::API credits exhausted" in capsys.readouterr().out
    result.refresh_from_db()
    assert result.status == "failed" and result.output_str == message
    assert list(snapshot.tags.values_list("pk", flat=True)) == tags_before


@pytest.mark.django_db
@pytest.mark.parametrize("message", ["OpenCode exited with status 1:", "Invalid API key", "Malformed provider output"])
def test_gallery_keeps_other_ai_failures_fatal(snapshot, message):
    from archivebox.core.library_screenshots import validate_ai_result

    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    with pytest.raises(RuntimeError, match="no successful autotag result"):
        validate_ai_result(snapshot, "autotag")


@pytest.mark.django_db
def test_gallery_requires_result_and_accepts_success(snapshot, capsys):
    from archivebox.core.library_screenshots import validate_ai_result

    with pytest.raises(RuntimeError, match="no successful autotag result"):
        validate_ai_result(snapshot, "autotag")
    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="succeeded", output_str="autotag/tags.jsonl")
    assert validate_ai_result(snapshot, "autotag") is True
    assert not capsys.readouterr().out


@pytest.mark.django_db
def test_gallery_features_complete_captures_and_retains_blocked_results(crawl, tmp_path):
    from archivebox.core.library_screenshots import select_gallery_snapshots
    from archivebox.core.models import Snapshot

    fixture = Path(__file__).parent / "fixtures"
    bodies = {
        "dom": ("output.html", gzip.decompress((fixture / "original-domain-replay/front.html.gz").read_bytes())),
        "screenshot": ("screenshot.png", (fixture / "redirected-image/image.png").read_bytes()),
        "archivewebpage": ("archivewebpage.wacz", (fixture / "memento/iframetest.wacz").read_bytes()),
    }
    urls = [f"https://example.com/{index}" for index in range(7)]
    snapshots = []
    for index, url in enumerate(urls):
        snapshot = Snapshot.objects.create(url=url, crawl=crawl, status="sealed", output_size=sum(len(body) for _, body in bodies.values()))
        snapshots.append(snapshot)
        for plugin, (filename, body) in bodies.items():
            output = snapshot.output_dir / plugin / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(body)
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin=plugin,
                status="succeeded",
                output_str=f"{plugin}/{filename}",
                output_files={filename: {"size": len(body)}},
                output_size=len(body),
            )
        navigation = snapshot.output_dir / "chrome/navigation.json"
        navigation.parent.mkdir()
        navigation.write_text(json.dumps({"url": url, "status": 403 if index == 1 else 200}))
    failed = ArchiveResult.objects.create(
        snapshot=snapshots[1],
        plugin="autotag",
        status="noresults",
        output_str="No saved text or HTML is available.",
    )
    featured = select_gallery_snapshots(snapshots, urls, tmp_path)
    assert [snapshot.url for snapshot in featured] == [urls[index] for index in (0, 2, 3, 4)]
    assert json.loads((tmp_path / "hacker-news-urls.json").read_text()) == [snapshot.url for snapshot in featured]
    records = json.loads((tmp_path / "hacker-news-captures.json").read_text())
    assert len(records) == 7 and records[1]["browser_status"] == 403 and not records[1]["eligible"]
    assert [record["replay_url"] for record in records] == urls
    assert records[1]["results"]["autotag"] == "noresults"
    failed.refresh_from_db()
    assert failed.status == "noresults"
    homepage_navigation = snapshots[0].output_dir / "chrome/navigation.json"
    homepage_navigation.write_text(json.dumps({"url": urls[0], "status": 403}))
    with pytest.raises(RuntimeError, match="successful homepage"):
        select_gallery_snapshots(snapshots, urls, tmp_path)
    homepage_navigation.write_text(json.dumps({"url": urls[0], "status": 200}))
    for snapshot in snapshots[4:]:
        (snapshot.output_dir / "archivewebpage/archivewebpage.wacz").unlink()
    with pytest.raises(RuntimeError, match="three captured stories"):
        select_gallery_snapshots(snapshots, urls, tmp_path)
