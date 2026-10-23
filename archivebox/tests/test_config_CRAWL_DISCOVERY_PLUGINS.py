"""Crawl discovery selection preserves parser artifacts and explicit seeds."""

import json

import pytest

from archivebox.config.common import ArchiveBoxConfig, get_config
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, parse_jsonl_output, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("discovery_plugins", ["parse_html_urls", " parse_html_urls,parse_dom_outlinks ", ""])
def test_cli_extract_limits_discovery_without_disabling_parsers(initialized_archive, httpserver, discovery_plugins):
    root = httpserver.url_for("/")
    article = httpserver.url_for("/article.pdf")
    discussion = httpserver.url_for("/item?id=123")
    profile = httpserver.url_for("/user?id=example")
    citation = httpserver.url_for("/citation")
    existing = httpserver.url_for("/existing")
    for route in ("/", "/article.pdf", "/item", "/citation", "/existing"):
        httpserver.expect_request(route).respond_with_data("<html><body>Saved article</body></html>", content_type="text/html")
    env = cli_env(PLUGINS="parse_html_urls,parse_txt_urls", CRAWL_DISCOVERY_PLUGINS=discovery_plugins)
    earlier = run_archivebox_cmd(["snapshot", "create", existing], cwd=initialized_archive, env=env)
    assert earlier.returncode == 0, earlier.stderr
    submitted = run_archivebox_cmd(
        ["snapshot", "create"],
        cwd=initialized_archive,
        env=env,
        input=json.dumps({"type": "Crawl", "urls": root, "max_depth": 1, "config": {"URL_DENYLIST": r"/user\?", "ONLY_NEW": True}}) + "\n",
    )
    assert submitted.returncode == 0, submitted.stderr
    parent_id = next(row["id"] for row in parse_jsonl_output(submitted.stdout) if row.get("type") == "Snapshot")
    updated = run_archivebox_cmd(
        ["snapshot", "update", "--tag=homepage"],
        cwd=initialized_archive,
        env=env,
        input=json.dumps({"type": "Snapshot", "id": parent_id}) + "\n",
    )
    assert updated.returncode == 0, updated.stderr
    with use_archivebox_db(initialized_archive):
        parent = Snapshot.objects.get(id=parent_id)
        source_dir = parent.output_dir
        crawl_id = parent.crawl_id
    # Replay saved page and attached-document text through the real hooks. The
    # PDF citation is content worth preserving, but is not a homepage anchor.
    page = source_dir / "dom/output.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        f'<html><body><a href="{article}">Article PDF</a><a href="{discussion}">Discuss</a><a href="{profile}">User</a><a href="{existing}">Earlier article</a></body></html>',
    )
    document = source_dir / "liteparse/article.pdf.txt"
    document.parent.mkdir(parents=True)
    document.write_text(f"Saved PDF text. References: {citation}\n")
    original_page = page.read_bytes()
    original_document = document.read_bytes()
    result = run_archivebox_cmd(
        ["extract", "--plugins=parse_html_urls,parse_txt_urls", parent_id],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    with use_archivebox_db(initialized_archive):
        children = set(Snapshot.objects.filter(crawl_id=crawl_id, depth=1).values_list("url", flat=True))
        expected = {article, discussion} | ({citation} if not discovery_plugins else set())
        assert children == expected
        parent = Snapshot.objects.select_related("crawl").get(id=parent_id)
        assert parent.depth == 0 and parent.url == root
        assert set(parent.tags.values_list("name", flat=True)) == {"homepage"}
        assert Snapshot.objects.filter(url=existing).count() == 1
        assert parent.crawl.config["CRAWL_DISCOVERY_PLUGINS"] == discovery_plugins
        assert get_config(crawl=parent.crawl).CRAWL_DISCOVERY_PLUGINS == discovery_plugins
        assert set(parent.archiveresult_set.values_list("plugin", "status")) == {
            ("parse_html_urls", ArchiveResult.StatusChoices.SUCCEEDED),
            ("parse_txt_urls", ArchiveResult.StatusChoices.SUCCEEDED),
        }
    html_records = [json.loads(line) for line in (source_dir / "parse_html_urls/urls.jsonl").read_text().splitlines()]
    text_records = [json.loads(line) for line in (source_dir / "parse_txt_urls/urls.jsonl").read_text().splitlines()]
    assert {row["url"] for row in html_records} == {article, discussion, profile, existing}
    assert {row["url"] for row in text_records} == {citation}
    assert page.read_bytes() == original_page
    assert document.read_bytes() == original_document
    assert ArchiveBoxConfig.scope_for_key("CRAWL_DISCOVERY_PLUGINS") == "crawl_frozen"


def test_discovery_provenance_comes_from_plugin_directory(tmp_path):
    from archivebox.plugins.hooks import collect_urls_from_plugins
    from archivebox.tests.test_cli_piping import run_real_txt_parser

    snapshot_dir = run_real_txt_parser(tmp_path, "https://archivebox.io/tests/citation")
    output = snapshot_dir / "parse_txt_urls/urls.jsonl"
    records = [json.loads(line) for line in output.read_text().splitlines()]
    for record in records:
        record["plugin"] = "parse_html_urls"
    output.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    discovered = collect_urls_from_plugins(snapshot_dir)
    assert [(record["url"], record["plugin"]) for record in discovered] == [
        ("https://archivebox.io/tests/citation", "parse_txt_urls"),
    ]
