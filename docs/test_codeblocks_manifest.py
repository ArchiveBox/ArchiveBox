"""Inventory, validate, and run the code examples in the authored documentation.

The docs stay written for people.  This scanner reads Markdown fences and the
README's deliberately hand-authored ``<pre lang="bash">`` examples without
requiring test directives in the prose.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "codeblocks.toml"
DISPOSITIONS = {"run", "illustration", "transcript", "output"}
ENVIRONMENT_RUNNERS = {
    "ubuntu": "ubuntu-24.04",
    "root": "ubuntu-24.04",
    "docker": "ubuntu-24.04",
    "macos": "macos-15",
    "freebsd": "ubuntu-24.04",
    "openbsd": "ubuntu-24.04",
}


class DocumentationTemporaryDirectory(tempfile.TemporaryDirectory):
    """Remove docs harness temp trees even when snippets create root-owned files."""

    def cleanup(self) -> None:
        if not self._finalizer.detach() and not Path(self.name).exists():
            return

        sudo = os.environ.get("SUDO_BINARY")
        if sudo and Path(sudo).is_file() and os.access(sudo, os.X_OK):
            subprocess.run(
                [sudo, "rm", "-rf", self.name],
                check=False,
            )
            return

        shutil.rmtree(self.name, ignore_errors=False)


CI_ENVIRONMENTS = {"ubuntu", "root", "docker", "macos"}
SCENARIOS = {"project", "collection", "system", "system-data", "docker", "docker-data"}
FENCE_START = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)$")
HTML_PRE = re.compile(
    r"""<pre\b(?=[^>]*\blang=(?:"(?:bash|sh|console)"|'(?:bash|sh|console)'|(?:bash|sh|console)\b))[^>]*>
        \s*<code\b[^>]*>(?P<code>.*?)</code>\s*</pre>""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Snippet:
    id: str
    path: str
    line: int
    style: str
    syntax: str
    code: str


def authored_markdown_paths() -> tuple[Path, ...]:
    candidates = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "archivebox" / "mcp" / "README.md"]
    candidates.extend(sorted((ROOT / "skills").rglob("*.md")))
    candidates.extend(sorted((ROOT / "docs").rglob("*.md")))

    paths: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if not path.is_file() or path.is_symlink() or "apidocs" in path.parts:
            continue
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(path)
    return tuple(paths)


def _masked_html_comments(text: str) -> str:
    chars = list(text)
    for match in HTML_COMMENT.finditer(text):
        for index in range(match.start(), match.end()):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _markdown_fences(text: str) -> list[tuple[int, str, str, str]]:
    original_lines = text.splitlines(keepends=True)
    masked_lines = _masked_html_comments(text).splitlines(keepends=True)
    found: list[tuple[int, str, str, str]] = []
    index = 0
    while index < len(masked_lines):
        start = FENCE_START.match(masked_lines[index].rstrip("\r\n"))
        if start is None:
            index += 1
            continue
        fence = start.group("fence")
        syntax = start.group("info").strip().split(maxsplit=1)[0].lower()
        if syntax.startswith("{.") and syntax.endswith("}"):
            syntax = syntax[2:-1]
        closing = re.compile(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        end = index + 1
        while end < len(masked_lines) and closing.match(masked_lines[end].rstrip("\r\n")) is None:
            end += 1
        if end == len(masked_lines):
            raise AssertionError(f"Unclosed Markdown fence at line {index + 1}")
        found.append((index + 1, "fence", syntax, "".join(original_lines[index + 1 : end]).rstrip("\r\n")))
        index = end + 1
    return found


def _html_pre_blocks(text: str) -> list[tuple[int, str, str, str]]:
    found = []
    for match in HTML_PRE.finditer(text):
        opening = text[match.start() : match.start("code")]
        language = re.search(r"""\blang=["']?(bash|sh|console)""", opening, re.IGNORECASE)
        assert language is not None
        code = re.sub(r"<br\s*/?>", "\n", match.group("code"), flags=re.IGNORECASE)
        code = re.sub(r"</?[^>]+>", "", code)
        found.append((text.count("\n", 0, match.start()) + 1, "html-pre", language.group(1).lower(), unescape(code).strip()))
    return found


def scan_snippets() -> tuple[Snippet, ...]:
    raw: list[tuple[str, int, str, str, str]] = []
    for path in authored_markdown_paths():
        relative_path = path.relative_to(ROOT).as_posix()
        text = path.read_text()
        blocks = _markdown_fences(text)
        blocks.extend(_html_pre_blocks(text))
        for line, style, syntax, code in sorted(blocks):
            raw.append((relative_path, line, style, syntax, code))

    hash_counts: dict[str, int] = {}
    snippets: list[Snippet] = []
    for path, line, style, syntax, code in raw:
        normalized = code.replace("\r\n", "\n").rstrip() + "\n"
        digest = sha256(f"{syntax}\0{normalized}".encode()).hexdigest()[:16]
        hash_counts[digest] = hash_counts.get(digest, 0) + 1
        snippets.append(
            Snippet(
                id=f"{digest}-{hash_counts[digest]}",
                path=path,
                line=line,
                style=style,
                syntax=syntax,
                code=code,
            ),
        )
    return tuple(snippets)


def load_manifest() -> dict[str, dict[str, str]]:
    with MANIFEST.open("rb") as manifest_file:
        document = tomllib.load(manifest_file)
    assert document.get("version") == 2
    records = {snippet_id: {"disposition": disposition} for snippet_id, disposition in document.get("snippets", {}).items()}
    for snippet_id, scenario in document.get("scenarios", {}).items():
        assert snippet_id in records
        records[snippet_id]["scenario"] = scenario
    for snippet_id, environment in document.get("environments", {}).items():
        assert snippet_id in records
        records[snippet_id]["environment"] = environment
    return records


def check_inventory() -> tuple[Snippet, ...]:
    snippets = scan_snippets()
    records = load_manifest()
    by_id = {snippet.id: snippet for snippet in snippets}
    assert set(records) == set(by_id), (
        f"Docs inventory is stale. Missing: {sorted(set(by_id) - set(records))}; removed: {sorted(set(records) - set(by_id))}"
    )

    for snippet in snippets:
        record = records[snippet.id]
        assert record.get("disposition") in DISPOSITIONS, f"{snippet.path}:{snippet.line}: missing disposition"
        if record["disposition"] == "run":
            assert record.get("scenario") in SCENARIOS, f"{snippet.id}: unknown run scenario"
            assert record.get("environment") in ENVIRONMENT_RUNNERS, f"{snippet.id}: unknown run environment"
        else:
            assert "scenario" not in record, f"{snippet.id}: non-running examples must not declare runtime setup"
            assert "environment" not in record, f"{snippet.id}: non-running examples must not declare a CI environment"
    return snippets


def validate_non_running(snippet: Snippet, disposition: str) -> None:
    assert snippet.code.strip(), f"{snippet.path}:{snippet.line}: empty code block"
    if disposition in {"transcript", "output"}:
        return
    if snippet.syntax in {"bash", "sh", "console"}:
        illustrative_shell = re.sub(r"<[A-Za-z][A-Za-z0-9_-]*>", "PLACEHOLDER", snippet.code)
        bash = Path(os.environ["BASH_BINARY"])
        assert bash.is_file() and os.access(bash, os.X_OK)
        result = subprocess.run([bash, "-n"], input=illustrative_shell, text=True, capture_output=True, check=False)
        assert result.returncode == 0, f"{snippet.path}:{snippet.line}: {result.stderr}"
    elif snippet.syntax in {"python", "python3"}:
        ast.parse(snippet.code, filename=f"{snippet.path}:{snippet.line}")
    elif snippet.syntax == "json":
        json.loads(snippet.code)
    elif snippet.syntax in {"yaml", "yml"}:
        import yaml

        illustrative_yaml = "\n".join(line for line in snippet.code.splitlines() if line.strip() != "...")
        list(yaml.safe_load_all(illustrative_yaml))
    elif snippet.syntax == "ini":
        parser = configparser.ConfigParser()
        parser.read_string(snippet.code)
    elif snippet.syntax == "sql":
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE auth_user "
            "(password, last_login, is_superuser, username, first_name, last_name, email, "
            "is_staff, is_active, date_joined)",
        )
        connection.executescript(snippet.code)
    elif snippet.syntax == "mermaid":
        assert snippet.code.lstrip().startswith(("stateDiagram", "flowchart", "graph", "sequenceDiagram"))
        mmdc = Path(os.environ["ABXPKG_LIB_DIR"]) / "env" / "bin" / "mmdc"
        assert mmdc.is_file() and os.access(mmdc, os.X_OK)
        with tempfile.TemporaryDirectory(prefix="archivebox-docs-mermaid-") as temp:
            source = Path(temp) / "diagram.mmd"
            output = Path(temp) / "diagram.svg"
            source.write_text(snippet.code)
            command = [mmdc, "--input", source, "--output", output]
            if sys.platform.startswith("linux"):
                command.extend(
                    [
                        "--puppeteerConfigFile",
                        ROOT / "docs" / "mermaid-puppeteer-linux.json",
                    ],
                )
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr or result.stdout
            assert output.stat().st_size > 0
    elif snippet.syntax == "nginx":
        assert snippet.code.count("{") == snippet.code.count("}")
        nginx = Path(os.environ["ABXPKG_LIB_DIR"]) / "env" / "bin" / "nginx"
        assert nginx.is_file() and os.access(nginx, os.X_OK)
        with tempfile.TemporaryDirectory(prefix="archivebox-docs-nginx-") as temp:
            config = Path(temp) / "nginx.conf"
            config.write_text(
                f"pid {temp}/nginx.pid;\n"
                f"error_log {temp}/error.log;\n"
                f"events {{}}\n"
                f"http {{\naccess_log {temp}/access.log;\nserver {{\nlisten 8080;\n{snippet.code}\n}}\n}}\n",
            )
            result = subprocess.run(
                [nginx, "-t", "-c", config, "-p", temp],
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr or result.stdout


def validate_all() -> tuple[Snippet, ...]:
    snippets = check_inventory()
    records = load_manifest()
    for snippet in snippets:
        disposition = records[snippet.id]["disposition"]
        if disposition != "run":
            try:
                validate_non_running(snippet, disposition)
            except Exception as error:
                raise AssertionError(
                    f"{snippet.path}:{snippet.line} ({snippet.id}, {disposition}) failed validation",
                ) from error
    return snippets


def matrix() -> dict[str, list[dict[str, str]]]:
    snippets = validate_all()
    records = load_manifest()
    runnable_snippets = [snippet for snippet in snippets if records[snippet.id]["disposition"] == "run"]
    by_environment = {
        environment: [snippet for snippet in runnable_snippets if records[snippet.id]["environment"] == environment]
        for environment in CI_ENVIRONMENTS
    }
    include: list[dict[str, str]] = []
    assigned_ids: list[str] = []
    for environment in ENVIRONMENT_RUNNERS:
        environment_snippets = by_environment.get(environment, [])
        if not environment_snippets:
            continue
        groups: dict[str, list[Snippet]] = {}
        if environment == "docker":
            groups[environment] = environment_snippets
        else:
            for snippet in environment_snippets:
                groups.setdefault(snippet.path, []).append(snippet)
        for group_name, group_snippets in groups.items():
            name_suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(group_name).with_suffix("").as_posix()).strip("-")
            include.append(
                {
                    "name": environment if group_name == environment else f"{environment}-{name_suffix}",
                    "environment": environment,
                    "runner": ENVIRONMENT_RUNNERS[environment],
                    "snippet_ids": " ".join(snippet.id for snippet in group_snippets),
                },
            )
            assigned_ids.extend(snippet.id for snippet in group_snippets)
    assert include, "At least one deterministic documentation example must run in CI"
    assert len(set(assigned_ids)) == len(assigned_ids)
    assert set(assigned_ids) == {snippet.id for snippet in runnable_snippets if records[snippet.id]["environment"] in CI_ENVIRONMENTS}, (
        "Every selected CI documentation snippet must have exactly one lane"
    )
    return {"include": include}


def run_environment(environment: str) -> None:
    assert environment in ENVIRONMENT_RUNNERS, f"Unknown documentation environment: {environment}"
    snippets = check_inventory()
    records = load_manifest()
    snippet_ids = tuple(
        snippet.id
        for snippet in snippets
        if records[snippet.id]["disposition"] == "run" and records[snippet.id]["environment"] == environment
    )
    assert snippet_ids, f"No documentation snippets are assigned to {environment}"
    run_snippets(snippet_ids)


def run_group(snippet_ids: str) -> None:
    parsed_ids = tuple(snippet_id for snippet_id in snippet_ids.split() if snippet_id)
    assert parsed_ids, "No documentation snippets were provided"
    run_snippets(parsed_ids)


def run_snippets(snippet_ids: tuple[str, ...]) -> None:
    snippets = {snippet.id: snippet for snippet in check_inventory()}
    records = load_manifest()
    assert len(set(snippet_ids)) == len(snippet_ids), "Each documentation snippet must run exactly once"
    for snippet_id in snippet_ids:
        assert snippet_id in snippets, f"Unknown snippet ID: {snippet_id}"
        assert records[snippet_id]["disposition"] == "run", f"{snippet_id} is classified as {records[snippet_id]['disposition']}"

    with DocumentationTemporaryDirectory(prefix="archivebox-docs-") as temp:
        temp_dir = Path(temp)
        temp_dir.chmod(0o755)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(temp_dir / "home"),
                "XDG_CACHE_HOME": str(temp_dir / "cache"),
                "XDG_CONFIG_HOME": str(temp_dir / "config"),
                "XDG_DATA_HOME": str(temp_dir / "share"),
                "UV_TOOL_BIN_DIR": str(temp_dir / "home" / ".local" / "bin"),
                "ABXPKG_LIB_DIR": str(temp_dir / "lib"),
                "PATH": f"{Path(sys.executable).parent}:{env['PATH']}",
            },
        )
        Path(env["HOME"]).mkdir()
        scenarios = {records[snippet_id]["scenario"] for snippet_id in snippet_ids}
        workdirs = {
            "project": ROOT,
            "collection": Path(env["HOME"]) / "archivebox" / "data",
            "docker": Path(env["HOME"]) / "archivebox",
            "docker-data": temp_dir / "data",
        }

        if "collection" in scenarios:
            workdirs["collection"].mkdir(parents=True, exist_ok=True)
            archivebox = Path(sys.executable).with_name("archivebox")
            assert archivebox.is_file() and os.access(archivebox, os.X_OK)
            subprocess.run(
                [archivebox, "init"],
                cwd=workdirs["collection"],
                env=env,
                check=True,
            )
        if scenarios.intersection({"docker", "docker-data"}):
            env["ARCHIVEBOX_IMAGE"] = "archivebox/archivebox:dev"
            docker = Path(env["DOCKER_BINARY"])
            assert docker.is_file() and os.access(docker, os.X_OK)
        if "docker" in scenarios:
            workdirs["docker"].mkdir(parents=True)
            (workdirs["docker"] / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
            subprocess.run(
                [docker, "compose", "run", "--rm", "archivebox", "init"],
                cwd=workdirs["docker"],
                env=env,
                check=True,
            )
        if "docker-data" in scenarios:
            workdirs["docker-data"].mkdir()
            subprocess.run(
                [docker, "run", "--rm", "-v", f"{workdirs['docker-data']}:/data", "archivebox/archivebox:dev", "init"],
                env=env,
                check=True,
            )

        root_checkout_import_root = temp_dir / "root-current-checkout"
        root_checkout_venv = temp_dir / "root-current-venv"
        root_checkout_python = root_checkout_venv / "bin" / "python"
        if any(records[snippet_id]["environment"] == "root" for snippet_id in snippet_ids):
            shutil.copytree(
                ROOT / "archivebox",
                root_checkout_import_root / "archivebox",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite3", "*.sqlite3-*"),
            )
            for copied_path in root_checkout_import_root.rglob("*"):
                copied_path.chmod(copied_path.stat().st_mode | (0o555 if copied_path.is_dir() else 0o444))
            root_checkout_import_root.chmod(root_checkout_import_root.stat().st_mode | 0o555)

        for snippet_id in snippet_ids:
            snippet = snippets[snippet_id]
            record = records[snippet_id]
            snippet_env = env.copy()
            launch_bash = Path(snippet_env.get("BASH_BINARY", env["BASH_BINARY"]))
            if record["scenario"] in {"system", "system-data"}:
                system_home = temp_dir / f"system-home-{snippet_id}"
                system_data_dir = system_home / "archivebox" / "data"
                system_home.mkdir()
                for inherited_binary in (
                    "BASH_BINARY",
                    "CURL_BINARY",
                    "DOCKER_BINARY",
                    "GIT_BINARY",
                    "JQ_BINARY",
                    "PYTHON_BINARY",
                    "SUDO_BINARY",
                    "UNAME_BINARY",
                    "UV_BINARY",
                    "WGET_BINARY",
                ):
                    snippet_env.pop(inherited_binary, None)
                for inherited_python_env in (
                    "PYTHONHOME",
                    "PYTHONPATH",
                    "UV_PROJECT_ENVIRONMENT",
                    "VIRTUAL_ENV",
                ):
                    snippet_env.pop(inherited_python_env, None)
                snippet_env.update(
                    {
                        "HOME": str(system_home),
                        "XDG_CACHE_HOME": str(system_home / ".cache"),
                        "XDG_CONFIG_HOME": str(system_home / ".config"),
                        "XDG_DATA_HOME": str(system_home / ".local" / "share"),
                        "UV_TOOL_BIN_DIR": str(system_home / ".local" / "bin"),
                        "ABXPKG_LIB_DIR": str(system_data_dir / "lib"),
                    },
                )
                system_lib_dir = Path(snippet_env["ABXPKG_LIB_DIR"])
                if record["environment"] == "root":
                    current_uv = Path(env["UV_BINARY"])
                    assert current_uv.is_file() and os.access(current_uv, os.X_OK)
                    local_bin_dir = system_home / ".local" / "bin"
                    local_bin_dir.mkdir(parents=True, exist_ok=True)
                    archivebox_wrapper = local_bin_dir / "archivebox"
                    archivebox_wrapper.write_text(
                        "#!/usr/bin/env bash\n"
                        f'if [[ ! -x "{root_checkout_python}" ]] || ! {root_checkout_python} -c "import rich.panel" >/dev/null 2>&1; then\n'
                        f"  (cd {ROOT} && UV_PROJECT_ENVIRONMENT={root_checkout_venv} {current_uv} --no-cache sync --locked --dev >/dev/null)\n"
                        f"  chmod -R a+rX {root_checkout_venv}\n"
                        "fi\n"
                        f'export PYTHONPATH="{root_checkout_import_root}${{PYTHONPATH:+:${{PYTHONPATH}}}}"\n'
                        f'export PATH="{root_checkout_python.parent}:$PATH"\n'
                        f'exec {root_checkout_python} -m archivebox "$@"\n',
                    )
                    archivebox_wrapper.chmod(0o755)
                    snippet_env["PATH"] = os.pathsep.join(
                        [
                            str(local_bin_dir),
                            str(system_home / ".cargo" / "bin"),
                            "/usr/local/sbin",
                            "/usr/local/bin",
                            "/usr/sbin",
                            "/usr/bin",
                            "/sbin",
                            "/bin",
                        ],
                    )
                else:
                    system_lib_dir.mkdir(parents=True, exist_ok=True)
                    system_lib_dir.chmod(0o777)
                    excluded_path_dirs = {Path(sys.executable).parent.resolve()}
                    if env.get("ABXPKG_LIB_DIR"):
                        excluded_path_dirs.add((Path(env["ABXPKG_LIB_DIR"]) / "env" / "bin").resolve())
                    snippet_env["PATH"] = os.pathsep.join(
                        [
                            str(system_home / ".local" / "bin"),
                            str(system_home / ".cargo" / "bin"),
                            *(part for part in env["PATH"].split(os.pathsep) if Path(part).resolve() not in excluded_path_dirs),
                        ],
                    )
                workdirs["system"] = temp_dir / f"system-cwd-{snippet_id}"
                workdirs["system-data"] = system_data_dir
                workdirs[record["scenario"]].mkdir(parents=True, exist_ok=True)
            print(f"Running {snippet.id}: {snippet.path}:{snippet.line} ({record['scenario']})", flush=True)
            if snippet.syntax in {"bash", "sh", "console"}:
                bash = launch_bash
                assert bash.is_file() and os.access(bash, os.X_OK)
                subprocess.run(
                    [bash, "-Eeuo", "pipefail", "-c", snippet.code],
                    cwd=workdirs[record["scenario"]],
                    env=snippet_env,
                    check=True,
                )
            elif snippet.syntax in {"python", "python3"}:
                subprocess.run(
                    [sys.executable, "-c", snippet.code],
                    cwd=workdirs[record["scenario"]],
                    env=snippet_env,
                    check=True,
                )
            else:
                raise AssertionError(f"{snippet.id}: {snippet.syntax} cannot have run disposition")


def render_manifest() -> None:
    existing: dict[str, dict[str, str | None]] = {}
    if MANIFEST.exists():
        with MANIFEST.open("rb") as manifest_file:
            document = tomllib.load(manifest_file)
        if document.get("version") == 2:
            existing = {
                snippet_id: {
                    "disposition": disposition,
                    "scenario": document.get("scenarios", {}).get(snippet_id),
                    "environment": document.get("environments", {}).get(snippet_id),
                }
                for snippet_id, disposition in document.get("snippets", {}).items()
            }
    lines = [
        "# Generated with: uv run --no-sync python docs/test_codeblocks_manifest.py render",
        "# Every authored occurrence is classified here without adding test plumbing to the rendered docs.",
        "version = 2",
        "",
        "[snippets]",
    ]
    snippets = scan_snippets()
    last_path = ""
    for snippet in snippets:
        old = existing.get(snippet.id, {})
        disposition = old.get("disposition", "illustration")
        if snippet.syntax in {"python", "python3"} and any(line.lstrip().startswith((">>>", "...")) for line in snippet.code.splitlines()):
            disposition = old.get("disposition", "transcript")
        if snippet.path != last_path:
            lines.extend(["", f"# {snippet.path}"])
            last_path = snippet.path
        lines.append(f"{json.dumps(snippet.id)} = {json.dumps(disposition)}")

    scenarios = {
        snippet.id: existing[snippet.id]["scenario"] for snippet in snippets if existing.get(snippet.id, {}).get("disposition") == "run"
    }
    environments = {
        snippet.id: existing[snippet.id]["environment"] for snippet in snippets if existing.get(snippet.id, {}).get("disposition") == "run"
    }
    lines.extend(["", "[scenarios]"])
    lines.extend(f"{json.dumps(snippet_id)} = {json.dumps(scenario)}" for snippet_id, scenario in scenarios.items())
    lines.extend(["", "[environments]"])
    lines.extend(f"{json.dumps(snippet_id)} = {json.dumps(environment)}" for snippet_id, environment in environments.items())
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "matrix", "run", "run-environment", "run-group", "render"))
    parser.add_argument("snippet_id", nargs="?")
    args = parser.parse_args()

    if args.command == "check":
        snippets = validate_all()
        print(f"Validated {len(snippets)} authored documentation snippets.")
    elif args.command == "matrix":
        print(json.dumps(matrix(), separators=(",", ":")))
    elif args.command == "run":
        assert args.snippet_id, "run requires a snippet ID"
        run_snippets((args.snippet_id,))
    elif args.command == "run-environment":
        assert args.snippet_id, "run-environment requires an environment"
        run_environment(args.snippet_id)
    elif args.command == "run-group":
        assert args.snippet_id, "run-group requires one or more snippet IDs"
        run_group(args.snippet_id)
    else:
        render_manifest()


if __name__ == "__main__":
    main()
