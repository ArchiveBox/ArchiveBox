"""Shared real import files and assertions for CLI, REST, and web add flows."""

import json
from pathlib import Path
from archivebox.core.models import Snapshot, SnapshotTag
from archivebox.tests.test_orm_helpers import use_archivebox_db

IMPORT_FORMAT_EXPECTATIONS = {
    "rss": {
        "url": "https://example.com/",
        "title": "RSS Example Import",
        "date": "2024-01-01",
        "tags": {"rss-tag", "metadata"},
    },
    "netscape": {
        "url": "https://www.iana.org/domains/reserved",
        "title": "IANA Reserved Domains",
        "date": "2024-01-02",
        "tags": {"netscape-tag", "metadata"},
    },
    "dom": {
        "url": "https://www.iana.org/help/example-domains",
    },
    "json": {
        "url": "https://example.com/?archivebox-json-import=1",
        "title": "JSON Import Example",
        "date": "2024-01-03",
        "tags": {"json-tag", "metadata"},
    },
    "jsonl": {
        "url": "https://example.com/?archivebox-jsonl-import=1",
        "title": "JSONL Import Example",
        "date": "2024-01-04",
        "tags": {"jsonl-tag", "metadata"},
    },
    "txt": {
        "url": "https://example.org/",
    },
}


def assert_expected_import_snapshots(
    cwd: Path,
    expected_urls: set[str],
    *,
    expected_tags: set[str] | None = None,
) -> None:
    allowed_statuses = {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    with use_archivebox_db(cwd):
        snapshots = list(Snapshot.objects.filter(url__in=expected_urls).values("id", "url", "status"))
        tag_names_by_snapshot_id = {}
        if expected_tags and snapshots:
            for snapshot_id, tag_name in SnapshotTag.objects.filter(
                snapshot_id__in=[snapshot["id"] for snapshot in snapshots],
            ).values_list("snapshot_id", "tag__name"):
                tag_names_by_snapshot_id.setdefault(snapshot_id, set()).add(tag_name)
    counts = {url: 0 for url in expected_urls}
    bad_statuses = []
    missing_tags = {}
    for snapshot in snapshots:
        counts[snapshot["url"]] += 1
        if snapshot["status"] not in allowed_statuses:
            bad_statuses.append((snapshot["url"], snapshot["status"]))
        if expected_tags:
            tag_names = tag_names_by_snapshot_id.get(snapshot["id"], set())
            missing = expected_tags - tag_names
            if missing:
                missing_tags[snapshot["url"]] = missing
    assert all(count == 1 for count in counts.values()), counts
    assert not bad_statuses, bad_statuses
    assert not missing_tags, missing_tags


def assert_no_file_or_shell_payload_snapshots(cwd: Path, *, canary: Path) -> None:
    with use_archivebox_db(cwd):
        snapshots = list(Snapshot.objects.all())
    assert not canary.exists()
    assert not [snapshot.url for snapshot in snapshots if str(snapshot.url).startswith("file:")]
    for forbidden in ("/etc/hosts", "/etc/passwd", "other_crawl_source", "archivebox_shell_injection_canary"):
        assert not [snapshot.url for snapshot in snapshots if forbidden in str(snapshot.url)]


def malicious_add_inputs(tmp_path: Path, *, safe_url: str) -> tuple[list[str], Path]:
    other_crawl_source = tmp_path / "sources" / "other_crawl_source.txt"
    other_crawl_source.parent.mkdir(parents=True, exist_ok=True)
    other_crawl_source.write_text("https://example.com/not-owned-by-this-crawl\n", encoding="utf-8")
    canary = tmp_path / "archivebox_shell_injection_canary"
    return (
        [
            safe_url,
            "file:///etc/hosts",
            "/etc/hosts",
            "../../../../etc/passwd",
            f"file://{other_crawl_source}",
            str(other_crawl_source),
            f"'; touch {canary}; #",
            f'" && touch {canary} && echo "',
            f"$(touch {canary})",
            f"`touch {canary}`",
            """<?xml version="1.0"?>
<!DOCTYPE rss [
  <!ENTITY localfile SYSTEM "file:///etc/hosts">
]>
<rss version="2.0" xmlns:xi="http://www.w3.org/2001/XInclude">
  <channel>
    <item><title>&localfile;</title><link>file:///etc/passwd</link></item>
    <xi:include href="file:///etc/hosts" parse="text"/>
  </channel>
</rss>""",
        ],
        canary,
    )


def write_import_format_files(base_dir: Path, urls: dict[str, str] | None = None) -> dict[str, Path]:
    urls = {
        "rss": "https://example.com/",
        "netscape": "https://www.iana.org/domains/reserved",
        "dom": "https://www.iana.org/help/example-domains",
        "json": "https://example.com/?archivebox-json-import=1",
        "jsonl": "https://example.com/?archivebox-jsonl-import=1",
        "txt": "https://example.org/",
        **(urls or {}),
    }
    files = {
        "rss": base_dir / "test_rss.xml",
        "netscape": base_dir / "test_netscape.html",
        "dom": base_dir / "test_dom.html",
        "json": base_dir / "test_bookmarks.json",
        "jsonl": base_dir / "test_bookmarks.jsonl",
        "txt": base_dir / "test_urls.txt",
    }
    files["rss"].write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ArchiveBox RSS import fixture</title>
    <link>{urls["rss"]}</link>
    <description>ArchiveBox RSS import fixture</description>
    <item>
      <title>RSS Example Import</title>
      <link>{urls["rss"]}</link>
      <guid>{urls["rss"]}</guid>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
      <category>rss-tag</category>
      <category>metadata</category>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    files["netscape"].write_text(
        f"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><A HREF="{urls["netscape"]}" ADD_DATE="1704153600" TAGS="netscape-tag,metadata">IANA Reserved Domains</A>
</DL><p>
""",
        encoding="utf-8",
    )
    files["dom"].write_text(
        f"""<!doctype html>
<html>
  <head><title>DOM import fixture</title></head>
  <body>
    <a href="{urls["dom"]}">IANA Example Domains</a>
  </body>
</html>
""",
        encoding="utf-8",
    )
    files["json"].write_text(
        json.dumps(
            {
                "url": urls["json"],
                "title": "JSON Import Example",
                "tags": ["json-tag", "metadata"],
                "bookmarked_at": "2024-01-03T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["jsonl"].write_text(
        json.dumps(
            {
                "url": urls["jsonl"],
                "title": "JSONL Import Example",
                "tags": "jsonl-tag,metadata",
                "bookmarked_at": "2024-01-04T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["txt"].write_text(
        f"Plain text import fixture containing {urls['txt']} as a real live URL.\n",
        encoding="utf-8",
    )
    return files
