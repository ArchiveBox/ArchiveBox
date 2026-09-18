"""Documentation source links must follow public model re-exports."""

import importlib
import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("module", "symbol", "expected_file", "declaration"),
    [
        ("archivebox.core.models", "Snapshot", "core/models/snapshots.py", "class Snapshot("),
        ("archivebox.core.models", "Snapshot.get_progress_stats", "core/models/snapshots.py", "def get_progress_stats("),
        ("archivebox.machine.models", "Process.to_json", "machine/models/processes.py", "def to_json("),
    ],
)
def test_public_model_source_link_targets_defining_file(module, symbol, expected_file, declaration):
    importlib.import_module(module)
    root = Path(__file__).resolve().parents[2]
    resolver = runpy.run_path(str(root / "docs/conf.py"))["linkcode_resolve"]
    url = resolver("py", {"module": module, "fullname": symbol})
    assert f"/archivebox/{expected_file}#L" in url
    line_number = int(url.split("#L", 1)[1].split("-", 1)[0])
    assert declaration in (root / "archivebox" / expected_file).read_text().splitlines()[line_number - 1]
    assert resolver("js", {"module": module, "fullname": symbol}) is None
