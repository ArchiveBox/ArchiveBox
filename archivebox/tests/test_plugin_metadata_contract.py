"""Declared result semantics apply to live presentation and filesystem repair."""

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("snapshot_output_order", True),
        ("snapshot_primary_preview", "true"),
        ("snapshot_thumbnail_cards", [{"archive_result_name": "title", "order": "0"}]),
        ("default_output_path", "../title.txt"),
        ("replay_assets", {"wacz": ["../secret"]}),
        ("archive_result_aliases", ["wget"]),
        ("archive_result_aliases", ["chrome_extension_viewport"]),
        ("snapshot_thumbnail_cards", [{"archive_result_name": "screenshot", "order": 0}]),
    ],
)
def test_cli_rejects_invalid_presentation_metadata_at_discovery(initialized_archive, tmp_path, key, value):
    import json
    import shutil
    from pathlib import Path

    from abx_plugins import get_plugins_dir
    from archivebox.tests.conftest import cli_env, run_archivebox_cmd

    plugins = tmp_path / "plugins"
    title = shutil.copytree(Path(get_plugins_dir()) / "title", plugins / "title")
    path = title / "config.json"
    config = json.loads(path.read_text())
    config[key] = value
    path.write_text(json.dumps(config))

    result = run_archivebox_cmd(["plugin", "--help"], env=cli_env(ABX_PLUGINS_DIR=str(plugins)))
    assert result.returncode != 0, result.stdout
    assert f"title: {key}" in result.stderr


def test_text_result_is_not_treated_as_a_filename():
    assert ArchiveResult.resolve_embed_path("title", "report.html", {}) is None
    assert ArchiveResult.resolve_embed_path("dns", "192.0.2.1", {}) is None


def test_text_result_rescan_recovers_manifest_without_following_its_value():
    crawl = Crawl.objects.create(urls="https://example.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/")
    directory = snapshot.output_dir / "title"
    directory.mkdir(parents=True)
    (directory / "title.txt").write_text("report.html")
    (snapshot.output_dir / "report.html").write_text("Unrelated file")
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="title", status="succeeded", output_str="report.html")
    assert result.update_output_metadata_from_filesystem()
    result.refresh_from_db()
    assert set(result.output_files) == {"title.txt"}
    assert result.output_size == len("report.html")
    assert result.output_str == "report.html"
    assert snapshot.resolved_title == "report.html"
    result.output_files = {}
    outputs = snapshot.discover_outputs(
        archive_results=[result],
        include_filesystem_fallback=True,
        filesystem_index={"report.html": {"size": 14}, "title/title.txt": {"size": 11}},
    )
    assert next(output["path"] for output in outputs if output["name"] == "title") == "title/title.txt"


def test_extra_cards_accept_plain_output_metadata():
    from abx_plugins.plugins.responses.presentation import extra_snapshot_output_cards

    cards = extra_snapshot_output_cards(
        [
            {
                "name": "responses",
                "path": "responses/index.html",
                "output_files": {"index.html": {"size": 12, "mimetype": "text/html"}},
            },
        ],
    )
    assert [card["name"] for card in cards] == ["responses_html"]
    assert cards[0]["path"] == "responses/index.html"
