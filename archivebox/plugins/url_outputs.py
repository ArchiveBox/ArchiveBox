"""The saved URL interface shared by crawl discovery and its read-only consumers."""

import os
from collections.abc import Iterator
from pathlib import Path

from archivebox.misc.jsonl import parse_line
from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url


def url_output_candidates(snapshot_dir: Path | int) -> Iterator[Path]:
    # The output directories belong to the capture. Its plugins may have been
    # disabled, renamed or uninstalled since it was saved.
    with os.scandir(snapshot_dir) as children:
        for child in children:
            if child.is_dir(follow_symlinks=False):
                yield Path(child.name, "urls.jsonl")


def parse_url_output(line: str, plugin: str) -> dict | None:
    record = parse_line(line)
    if record and record.get("type") and record.get("url"):
        url = sanitize_extracted_url(fix_url_from_markdown(str(record["url"]).strip()))
        if url:
            return {**record, "url": url, "plugin": plugin}
    return None
