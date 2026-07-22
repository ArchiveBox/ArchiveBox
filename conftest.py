from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest


DOCS_MANIFEST = Path(__file__).parent / "docs" / "codeblocks.toml"


def _load_docs_manifest() -> dict[str, Any]:
    with DOCS_MANIFEST.open("rb") as manifest_file:
        return tomllib.load(manifest_file)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--docs-environment",
        action="store",
        default=None,
        help="Run Markdown code blocks assigned to one docs CI environment.",
    )


def pytest_configure(config: pytest.Config) -> None:
    manifest = _load_docs_manifest()
    for environment in manifest["environments"]:
        config.addinivalue_line(
            "markers",
            f"docs_environment_{environment}: Markdown code block assigned to the {environment} CI environment",
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    manifest = _load_docs_manifest()
    environments = set(manifest["environments"])
    selected_environment = config.getoption("--docs-environment")
    if selected_environment is not None and selected_environment not in environments:
        raise pytest.UsageError(
            f"Unknown docs environment {selected_environment!r}; expected one of {sorted(environments)}",
        )

    file_environments = manifest["files"]
    block_environments = manifest["blocks"]
    collected_nodeids: set[str] = set()
    collected_paths: set[str] = set()
    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []

    for item in items:
        if item.path.suffix != ".md":
            selected.append(item)
            continue

        nodeid = item.nodeid
        collected_nodeids.add(nodeid)
        relative_path = item.path.resolve().relative_to(config.rootpath.resolve()).as_posix()
        collected_paths.add(relative_path)
        canonical_nodeid = f"{relative_path}::{nodeid.partition('::')[2]}"
        environment = block_environments.get(canonical_nodeid, file_environments.get(relative_path))
        if environment is None:
            raise pytest.UsageError(f"Markdown code block has no docs environment: {nodeid}")
        if environment not in environments:
            raise pytest.UsageError(f"Markdown code block has unknown docs environment {environment!r}: {nodeid}")

        item.add_marker(f"docs_environment_{environment}")
        if selected_environment is not None and environment != selected_environment:
            deselected.append(item)
        else:
            selected.append(item)

    stale_blocks = {nodeid for nodeid in block_environments if nodeid.partition("::")[0] in collected_paths} - collected_nodeids
    if stale_blocks and collected_nodeids:
        raise pytest.UsageError(f"Docs manifest contains stale code block ids: {sorted(stale_blocks)}")

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
