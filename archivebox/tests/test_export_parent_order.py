# ruff: noqa: F811 - pytest injects the imported shared capture fixture by name.
"""Archive exports prioritize directly saved pages within their existing batches."""

import json
from zipfile import ZipFile

import pytest
from django.core.management import call_command

from archivebox.tests.test_original_domain_replay import saved_site  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("format", ["html", "html_zip"])
def test_export_prioritizes_parentless_pages_without_changing_selection(saved_site, tmp_path, format):
    root, child, other_root = (snapshot for snapshot, _, _ in saved_site)
    child.parent_snapshot = root
    child.save(update_fields=["parent_snapshot"])
    destination = tmp_path / "export"
    call_command(
        "site_export",
        query="domain=news.ycombinator.com&sort=-url,-id",
        format=format,
        destination=str(destination),
    )
    # The URL sort puts the child first. Prefer both directly saved pages, but
    # preserve that requested URL order among the pages with no parent.
    expected = [other_root.url, root.url, child.url]
    if format == "html_zip":
        with ZipFile(destination / "site.zip") as archive:
            pages = json.loads(archive.read("pages.json"))
            records = archive.read("index.jsonl").splitlines()
    else:
        pages = json.loads((destination / "pages.json").read_text())
        records = (destination / "index.jsonl").read_text().splitlines()
    assert [page["url"] for page in pages] == expected
    assert [json.loads(record)["url"] for record in records] == expected
    for _, source, original in saved_site:
        assert source.read_bytes() == original
