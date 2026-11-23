"""Installed replay viewers attribute originals without changing saved outputs."""

import cProfile
import pstats
from html.parser import HTMLParser
from pathlib import Path

import pytest
from abx_plugins import get_plugins_dir

from archivebox.plugins.discovery import add_replay_document_metadata


class HeadMetadata(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.links = []
        self.robots = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") in {"canonical", "original"}:
            self.links.append((values["rel"], values.get("href")))
        if tag == "meta" and values.get("name") == "robots":
            self.robots.append(values.get("content"))


def assert_metadata(document, original):
    head = HeadMetadata(document)
    assert head.links == [("canonical", original), ("original", original)]
    assert head.robots == ["noindex, follow"]


@pytest.mark.parametrize(
    "head",
    [
        '<!doctype html><html><head><meta charset="utf-8"></head>',
        '<!DOCTYPE html><HTML><HEAD><LINK REL="canonical" href="wrong"><link rel="original" href="wrong">'
        '<META NAME="ROBOTS" content="index, nofollow"></HEAD>',
        '<html><meta name="robots" content="none">',
        '<!doctype html><!-- <meta name="robots" content="none"> --><html><head>'
        '<script>const example = \'</head><link rel="canonical" href="example">\';</script></head>',
        "<html><head>\n" + (" " * 4100) + '<link\n rel="canonical" href="wrong"></head>',
    ],
)
def test_replay_metadata_replaces_conflicts_and_preserves_body(head):
    original = 'https://example.org/page?one="quoted"&two=<value>'
    body = '<body><p>Saved content</p><script>const html = "<head>";</script></body></html>'
    document = add_replay_document_metadata(head + body, original)
    assert_metadata(document, original)
    assert document.endswith(body)
    assert add_replay_document_metadata(document, original) is document


@pytest.mark.parametrize("head", ["<html><head></head><body>", "<!doctype html><html>"])
def test_replay_metadata_does_not_parse_large_saved_body(head):
    body = "<p>Saved page</p>" * 100_000
    profile = cProfile.Profile()
    with profile:
        document = add_replay_document_metadata(head + body + "</body></html>", "https://example.org/")
    callbacks = sum(
        values[1]
        for (source, _line, function), values in pstats.Stats(profile).stats.items()
        if source.endswith("plugins/discovery.py") and function == "handle_starttag"
    )
    assert callbacks < 300
    assert document.endswith(body + "</body></html>")


@pytest.mark.django_db
@pytest.mark.parametrize("plugin", sorted(path.parent.parent.name for path in Path(get_plugins_dir()).glob("*/templates/full.html")))
def test_every_installed_full_template_attributes_original(snapshot, plugin):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.templatetags.core_tags import render_plugin_full_document

    result = ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="succeeded", output_str="output.txt")
    document = render_plugin_full_document(
        snapshot,
        f"{plugin}/output.txt",
        result,
        output_url=f"/{plugin}/output.txt",
        snapshot_details_url="/index.html",
    )
    assert_metadata(document, snapshot.url)


def test_custom_wacz_renderer_attributes_original_and_preserves_archive():
    from archivebox.plugins.discovery import render_plugin_full_response

    source = Path(__file__).parent / "fixtures/memento/iframetest.wacz"
    saved = source.read_bytes()
    original = "https://example.org/original?one=1&two=2"
    document, content_type, headers = render_plugin_full_response(
        source.name,
        "/archivewebpage/capture.wacz",
        source_path=source,
        fallback_url=original,
        replay_base="/replay/",
    )
    assert content_type == "text/html; charset=utf-8"
    assert_metadata(document, original)
    assert "Content-Security-Policy" in headers
    assert source.read_bytes() == saved
