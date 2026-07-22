import configparser
from collections import Counter
import json
from pathlib import Path
import sqlite3
import subprocess
import tomllib

from pytest_codeblocks.main import extract_from_file
import yaml


REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "codeblocks.toml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def markdown_paths() -> tuple[Path, ...]:
    candidates = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "archivebox" / "mcp" / "README.md",
    ]
    candidates.extend(sorted((REPO_ROOT / "skills").rglob("*.md")))
    candidates.extend(sorted((REPO_ROOT / "docs").rglob("*.md")))

    unique_paths: dict[Path, Path] = {}
    for path in candidates:
        unique_paths.setdefault(path.resolve(), path)
    return tuple(unique_paths.values())


def docs_blocks() -> dict[str, object]:
    return {
        f"{path.relative_to(REPO_ROOT).as_posix()}::line {block.lineno}": block
        for path in markdown_paths()
        for block in extract_from_file(path)
    }


def test_every_executable_docs_block_has_exactly_one_ci_environment() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        manifest = tomllib.load(manifest_file)

    environments = set(manifest["environments"])
    executable_syntaxes = set(manifest["syntax"]["executed"])
    file_environments = manifest["files"]
    block_environments = manifest["blocks"]
    discovered: dict[str, str] = {}

    executable_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in markdown_paths()
        if any(block.syntax in executable_syntaxes for block in extract_from_file(path))
    }

    assert set(file_environments) == executable_files

    for relative_path in sorted(executable_files):
        file_environment = file_environments[relative_path]
        assert file_environment in environments
        path = REPO_ROOT / relative_path
        assert path.is_file(), relative_path
        for block in extract_from_file(path):
            if block.syntax not in executable_syntaxes:
                continue
            nodeid = f"{relative_path}::line {block.lineno}"
            environment = block_environments.get(nodeid, file_environment)
            assert environment in environments, nodeid
            assert nodeid not in discovered
            discovered[nodeid] = environment

    assert set(block_environments) <= set(discovered)
    assert set(discovered.values()) == environments


def test_every_docs_fence_syntax_is_explicitly_classified() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        syntax_manifest = tomllib.load(manifest_file)["syntax"]

    classified = set(syntax_manifest["executed"])
    classified.update(syntax_manifest["shell_syntax_only"])
    classified.update(syntax_manifest["structured"])
    classified.update(syntax_manifest["prose"])
    directive_prefixes = tuple(syntax_manifest["directive_prefixes"])

    unknown = {
        f"{nodeid} ({block.syntax!r})"
        for nodeid, block in docs_blocks().items()
        if block.syntax not in classified and not block.syntax.startswith(directive_prefixes)
    }
    assert not unknown


def test_every_console_fence_is_inventoried_and_shell_parseable() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        expected_console_blocks = set(tomllib.load(manifest_file)["syntax"]["console_blocks"])

    console_blocks = {nodeid: block for nodeid, block in docs_blocks().items() if block.syntax == "console"}
    assert set(console_blocks) == expected_console_blocks
    for nodeid, block in console_blocks.items():
        result = subprocess.run(["bash", "-n"], input=block.code, text=True, capture_output=True, check=False)
        assert result.returncode == 0, f"{nodeid}: {result.stderr}"


def test_structured_data_fences_parse() -> None:
    blocks = docs_blocks()
    sql_connection = sqlite3.connect(":memory:")
    sql_connection.execute(
        "CREATE TABLE auth_user (password, last_login, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined)",
    )

    for nodeid, block in blocks.items():
        if block.syntax == "json":
            json.loads(block.code)
        elif block.syntax == "yaml":
            list(yaml.safe_load_all(block.code))
        elif block.syntax == "ini":
            parser = configparser.ConfigParser()
            parser.read_string(block.code)
        elif block.syntax == "sql":
            try:
                sql_connection.executescript(block.code)
            except sqlite3.Error as err:
                raise AssertionError(nodeid) from err


def test_mermaid_fences_render_with_resolved_mmdc(tmp_path: Path) -> None:
    mermaid_blocks = [(nodeid, block) for nodeid, block in docs_blocks().items() if block.syntax == "mermaid"]
    assert len(mermaid_blocks) == 4
    for index, (nodeid, block) in enumerate(mermaid_blocks):
        source = tmp_path / f"diagram-{index}.mmd"
        output = tmp_path / f"diagram-{index}.svg"
        source.write_text(block.code)
        result = subprocess.run(["mmdc", "--input", source, "--output", output], text=True, capture_output=True, check=False)
        assert result.returncode == 0, f"{nodeid}: {result.stderr}"
        assert output.stat().st_size > 0


def test_nginx_fence_parses_with_resolved_nginx(tmp_path: Path) -> None:
    nginx_blocks = [(nodeid, block) for nodeid, block in docs_blocks().items() if block.syntax == "nginx"]
    assert len(nginx_blocks) == 1
    nodeid, block = nginx_blocks[0]
    config = tmp_path / "nginx.conf"
    config.write_text(f"events {{}}\nhttp {{\nserver {{\nlisten 8080;\n{block.code}\n}}\n}}\n")
    result = subprocess.run(
        ["nginx", "-t", "-c", str(config), "-p", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{nodeid}: {result.stderr}"


def test_docs_ci_matrix_covers_every_manifest_environment() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        manifest = tomllib.load(manifest_file)

    environments = set(manifest["environments"])
    standard_environments = set(manifest["ci"]["standard"])
    bsd_environments = set(manifest["ci"]["bsd"])
    assert standard_environments.isdisjoint(bsd_environments)
    assert standard_environments | bsd_environments == environments

    workflow = WORKFLOW_PATH.read_text()
    assert "pytest -q docs/test_codeblocks_manifest.py" in workflow
    assert "--docs-environment=${{ matrix.environment }}" in workflow
    assert "DOCS_CORE_SHARD: ${{ matrix.core_shard }}" in workflow
    for environment in bsd_environments:
        assert f"--docs-environment={environment}" in workflow


def test_every_core_file_belongs_to_exactly_one_explicit_shard() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        manifest = tomllib.load(manifest_file)

    file_environments = manifest["files"]
    block_environments = manifest["blocks"]
    core_files = {path for path, environment in file_environments.items() if environment == "core"}
    core_files.update(nodeid.partition("::")[0] for nodeid, environment in block_environments.items() if environment == "core")

    core_shards = manifest["ci"]["core_shards"]
    assert core_shards
    shard_members = [path for paths in core_shards.values() for path in paths]
    member_counts = Counter(shard_members)

    assert set(shard_members) == core_files
    assert {path: count for path, count in member_counts.items() if count != 1} == {}
