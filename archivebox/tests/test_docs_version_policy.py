"""Version selection uses numeric release ordering across actual ArchiveBox tags."""

import runpy
from pathlib import Path


def test_docs_picker_keeps_latest_rc_and_historical_patch_per_minor():
    select = runpy.run_path(str(Path(__file__).resolve().parents[2] / "bin/sync_docs_versions.py"))["selected_tags"]
    tags = [
        "v0.9.35rc99",
        "v0.9.35rc469",
        "v0.9.31-rc",
        "v0.8.5-rc",
        "v0.8.6rc1",
        "v0.7.3",
        "v0.7.4",
        "v0.6.0",
        "v0.6.2",
        "v0.5.4",
        "v0.5.6",
        "v0.4.9",
        "v0.4.24",
        "v0.2.4",
        "v0.1.0",
        "v0.0.3",
    ]
    assert select(tags) == [
        "v0.9.35rc469",
        "v0.8.6rc1",
        "v0.7.4",
        "v0.6.2",
        "v0.5.6",
        "v0.4.24",
        "v0.2.4",
        "v0.1.0",
        "v0.0.3",
    ]
    assert select(reversed(tags)) == select(tags)
