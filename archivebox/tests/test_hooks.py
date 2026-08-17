#!/usr/bin/env python3
"""
Unit tests for the ArchiveBox hook architecture.

Tests hook discovery, execution, JSONL parsing, background hook detection,
binary lookup, and required_binaries XYZ_BINARY passthrough handling.

Run with:
    sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_hooks.py -v'
"""

import json
import hashlib
import os
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

from archivebox.tests.conftest import install_real_binary, resolve_abxpkg_binary_env

# Set up Django before importing any Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.settings")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
WGET_CONFIG = Path(str(files("abx_plugins.plugins.wget").joinpath("config.json")))
CHROME_CONFIG = Path(str(files("abx_plugins.plugins.chrome").joinpath("config.json")))


def test_cli_env_does_not_emit_relative_pythonpath_entries():
    from archivebox.tests.conftest import cli_env

    old_pythonpath = os.environ.get("PYTHONPATH")
    try:
        os.environ["PYTHONPATH"] = os.pathsep.join(
            ["../abxpkg", "../abx-plugins", "../abx-dl", "/nonexistent/archivebox-pythonpath"],
        )

        env = cli_env()
    finally:
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath

    pythonpath_entries = {Path(entry) for entry in env["PYTHONPATH"].split(os.pathsep)}
    assert REPO_ROOT.resolve() in pythonpath_entries
    for repo_name in ("abxpkg", "abx-plugins", "abx-dl"):
        repo_path = next((path for path in (WORKSPACE_ROOT / repo_name, REPO_ROOT / repo_name) if path.exists()), None)
        if repo_path is not None:
            assert repo_path.resolve() in pythonpath_entries
    assert all(path.is_absolute() and path.exists() for path in pythonpath_entries)


class TestBackgroundHookDetection:
    """Test background classification against the shipped hook suite."""

    def test_shipped_hooks_are_classified_by_bg_marker(self):
        from archivebox.plugins.hooks import discover_hooks, is_background_hook

        hooks = discover_hooks("Snapshot", filter_disabled=False)
        background_hooks = [hook for hook in hooks if is_background_hook(hook.name)]
        foreground_hooks = [hook for hook in hooks if not is_background_hook(hook.name)]

        assert hooks
        assert background_hooks
        assert foreground_hooks
        assert all(".bg." in hook.name for hook in background_hooks)
        assert all(".bg." not in hook.name for hook in foreground_hooks)
        assert any(hook.name == "on_Snapshot__01_chrome_tab.daemon.bg.js" for hook in background_hooks)
        assert any(hook.name == "on_Snapshot__35_wget.finite.bg.py" for hook in background_hooks)
        assert any(hook.name == "on_Snapshot__93_hashes.py" for hook in foreground_hooks)


@pytest.mark.django_db(transaction=True)
class TestJSONLParsing:
    """Test JSONL parsing against output from shipped hooks."""

    @staticmethod
    def run_hashes_hook(tmp_path):
        from archivebox.plugins.hooks import run_hook

        snap_dir = tmp_path / "hash-snapshot"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("real parser input", encoding="utf-8")
        hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
        process = run_hook(
            hook_path,
            output_dir,
            config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
            timeout=30,
            url="https://example.com/hash-parser",
        )
        process.refresh_from_db()
        assert process.exit_code == 0, process.stderr
        return process

    @staticmethod
    def run_parser_hook(tmp_path):
        from archivebox.plugins.hooks import run_hook

        snap_dir = tmp_path / "parser-snapshot"
        staticfile_dir = snap_dir / "staticfile"
        output_dir = snap_dir / "parse_txt_urls"
        staticfile_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        (staticfile_dir / "input.txt").write_text(
            "links: https://one.example/path and https://two.example/path",
            encoding="utf-8",
        )
        hook_path = Path(str(files("abx_plugins.plugins.parse_txt_urls").joinpath("on_Snapshot__71_parse_txt_urls.py")))
        process = run_hook(
            hook_path,
            output_dir,
            config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
            timeout=30,
            url="file:///input.txt",
        )
        process.refresh_from_db()
        assert process.exit_code == 0, process.stderr
        return process

    def test_parse_clean_jsonl(self, tmp_path):
        """Clean JSONL emitted by a shipped hook should be parsed correctly."""
        from archivebox.machine.models import Process

        process = self.run_hashes_hook(tmp_path)
        records = Process.parse_records_from_text(process.stdout)

        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == "succeeded"
        assert records[0]["output_str"].endswith(hashlib.sha256(b"real parser input").hexdigest()[:12])

    def test_parse_multiple_jsonl_records(self, tmp_path):
        """Every record emitted by a shipped parser hook should be parsed."""
        from archivebox.machine.models import Process

        process = self.run_parser_hook(tmp_path)
        records = Process.parse_records_from_text(process.stdout)

        assert [record["type"] for record in records] == ["Snapshot", "Snapshot", "ArchiveResult"]
        assert {record["url"] for record in records[:-1]} == {
            "https://one.example/path",
            "https://two.example/path",
        }
        assert records[-1]["status"] == "succeeded"

    def test_parse_jsonl_with_log_output(self, tmp_path):
        """JSONL should be extracted from a shipped hook's mixed stdout."""
        from archivebox.machine.models import Process

        process = self.run_parser_hook(tmp_path)
        assert "parsing 1 files for urls..." in process.stdout
        assert "2 URLs parsed" in process.stdout
        records = Process.parse_records_from_text(process.stdout)

        assert len(records) == 3
        assert records[-1]["status"] == "succeeded"

    def test_ignore_invalid_json(self, tmp_path):
        """Malformed non-record lines must not hide real hook records."""
        from archivebox.machine.models import Process

        process = self.run_hashes_hook(tmp_path)
        stdout = f"{process.stdout}\n{{invalid json here}}\nnot json at all\n"
        records = Process.parse_records_from_text(stdout)

        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"

    def test_json_without_type_ignored(self, tmp_path):
        """A non-record object must not hide the shipped hook's real record."""
        from archivebox.machine.models import Process

        process = self.run_hashes_hook(tmp_path)
        records = Process.parse_records_from_text(f'{process.stdout}\n{{"status":"succeeded"}}\n')

        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"


class TestRequiredBinaryConfigHandling:
    """Test that required_binaries keep configured XYZ_BINARY values intact."""

    @pytest.mark.django_db(transaction=True)
    def test_binary_env_var_absolute_path_handling(self, hermetic_lib_dir):
        """abxpkg should expose the resolved binary as an absolute path."""
        install_real_binary("wget", binproviders="env,apt,brew")
        resolved = resolve_abxpkg_binary_env(hermetic_lib_dir, deps_from=WGET_CONFIG)

        assert Path(resolved["WGET_BINARY"]).is_absolute()
        assert Path(resolved["WGET_BINARY"]).is_file()

    @pytest.mark.django_db(transaction=True)
    def test_binary_env_var_name_only_handling(self, hermetic_lib_dir):
        """The projected command name should execute the resolved host binary."""
        lib_dir = hermetic_lib_dir
        install_real_binary("wget", binproviders="env,apt,brew")
        resolve_abxpkg_binary_env(lib_dir, deps_from=WGET_CONFIG)
        projection = lib_dir / "env" / "bin" / "wget"
        result = subprocess.run([projection, "--version"], capture_output=True, text=True)

        assert projection.is_symlink()
        assert result.returncode == 0, result.stderr
        assert "Wget" in result.stdout

    def test_binary_env_var_empty_default(self):
        """The shipped wget schema should retain wget as its required binary."""
        config = json.loads(files("abx_plugins.plugins.wget").joinpath("config.json").read_text())

        assert config["required_binaries"][0]["name"] == "{WGET_BINARY}"
        assert config["properties"]["WGET_BINARY"]["default"] == "wget"


class TestHookDiscovery:
    """Test hook discovery functions."""

    def test_discover_hooks_by_event(self):
        """discover_hooks() should find all hooks for an event."""
        from archivebox.plugins.hooks import discover_hooks

        hooks = discover_hooks("Snapshot", filter_disabled=False)

        hook_names = [h.name for h in hooks]
        assert "on_Snapshot__01_chrome_tab.daemon.bg.js" in hook_names
        assert "on_Snapshot__21_consolelog.daemon.bg.js" in hook_names
        assert "on_Snapshot__35_wget.finite.bg.py" in hook_names
        assert all(hook.is_file() for hook in hooks)

    def test_discover_hooks_sorted_by_name(self):
        """Hooks should be sorted by filename (numeric prefix ordering)."""
        from archivebox.plugins.hooks import discover_hooks

        hook_names = [hook.name for hook in discover_hooks("Snapshot", filter_disabled=False)]
        assert hook_names == sorted(hook_names)

    def test_normalize_hook_event_name_accepts_event_classes(self):
        """Hook discovery should normalize bus event class names to hook families."""
        from archivebox.plugins import hooks as hooks_module

        assert hooks_module.normalize_hook_event_name("InstallEvent") == "Install"
        assert hooks_module.normalize_hook_event_name("BinaryRequestEvent") == "BinaryRequest"
        assert hooks_module.normalize_hook_event_name("CrawlSetupEvent") == "CrawlSetup"
        assert hooks_module.normalize_hook_event_name("SnapshotEvent") == "Snapshot"

    def test_normalize_hook_event_name_strips_event_suffix_for_lifecycle_events(self):
        """Lifecycle event names should normalize via simple suffix stripping."""
        from archivebox.plugins import hooks as hooks_module

        assert hooks_module.normalize_hook_event_name("BinaryEvent") == "Binary"
        assert hooks_module.normalize_hook_event_name("CrawlEvent") == "Crawl"
        assert hooks_module.normalize_hook_event_name("SnapshotCleanupEvent") == "SnapshotCleanup"
        assert hooks_module.normalize_hook_event_name("CrawlCleanupEvent") == "CrawlCleanup"

    def test_discover_hooks_skips_plugins_with_disabled_required_dependencies(self):
        """Plugins whose required_plugins are disabled should not run."""
        from archivebox.plugins.hooks import discover_hooks

        hook_names = [hook.parent.name for hook in discover_hooks("Snapshot", config={"CHROME_ENABLED": False, "WGET_ENABLED": True})]
        assert "wget" in hook_names
        assert "chrome" not in hook_names
        assert "accessibility" not in hook_names

    def test_get_plugins_includes_config_only_plugin_dirs(self):
        """get_plugins() should include shipped plugin directories without hooks."""
        from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, get_plugins

        plugins = get_plugins()
        assert "base" in plugins
        base_dir = BUILTIN_PLUGINS_DIR / "base"
        assert (base_dir / "config.json").is_file()
        assert list(base_dir.glob("on_*__*.*")) == []

    def test_discover_binary_hooks_returns_empty(self):
        """Binary provider hooks are owned by abxpkg, not ArchiveBox plugin discovery."""
        from archivebox.plugins.hooks import discover_hooks

        hook_names = [hook.name for hook in discover_hooks("BinaryRequest", filter_disabled=False)]
        assert hook_names == []

    def test_discover_hooks_accepts_event_class_names(self):
        """discover_hooks should accept CrawlSetupEvent / SnapshotEvent class names."""
        from archivebox.plugins.hooks import discover_hooks

        hook_names = {
            "crawl_setup": [hook.name for hook in discover_hooks("CrawlSetupEvent", filter_disabled=False)],
            "snapshot": [hook.name for hook in discover_hooks("SnapshotEvent", filter_disabled=False)],
        }
        assert "on_CrawlSetup__90_chrome_launch.daemon.bg.js" in hook_names["crawl_setup"]
        assert "on_Snapshot__35_wget.finite.bg.py" in hook_names["snapshot"]

    def test_discover_hooks_returns_empty_for_non_hook_lifecycle_events(self):
        """Lifecycle events without a hook family should return no hooks."""
        from archivebox.plugins.hooks import discover_hooks

        hooks = {
            "binary": [hook.name for hook in discover_hooks("BinaryEvent", filter_disabled=False)],
            "crawl_cleanup": [hook.name for hook in discover_hooks("CrawlCleanupEvent", filter_disabled=False)],
        }
        assert hooks["binary"] == []
        assert hooks["crawl_cleanup"] == []


class TestGetExtractorName:
    """Test get_extractor_name() function."""

    def test_strip_numeric_prefix(self):
        """Numeric prefix should be stripped from extractor name."""

        # Inline implementation of get_extractor_name
        def get_extractor_name(extractor: str) -> str:
            parts = extractor.split("_", 1)
            if len(parts) == 2 and parts[0].isdigit():
                return parts[1]
            return extractor

        assert get_extractor_name("10_title") == "title"
        assert get_extractor_name("26_readability") == "readability"
        assert get_extractor_name("50_parse_html_urls") == "parse_html_urls"

    def test_no_prefix_unchanged(self):
        """Extractor without numeric prefix should be unchanged."""

        def get_extractor_name(extractor: str) -> str:
            parts = extractor.split("_", 1)
            if len(parts) == 2 and parts[0].isdigit():
                return parts[1]
            return extractor

        assert get_extractor_name("title") == "title"
        assert get_extractor_name("readability") == "readability"


class TestHookExecution:
    """Test hook execution with real subprocesses."""

    def test_python_hook_execution(self, tmp_path):
        """Python hook should execute and output JSONL."""
        snap_dir = tmp_path / "snapshot"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("real hook input", encoding="utf-8")
        hook_path = Path(
            str(
                files("abx_plugins.plugins.hashes").joinpath(
                    "on_Snapshot__93_hashes.py",
                ),
            ),
        )

        result = subprocess.run(
            [str(hook_path), "--url=https://example.com"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            env={**os.environ, "SNAP_DIR": str(snap_dir)},
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(result.stdout)
        assert records
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == "succeeded"

    @pytest.mark.django_db(transaction=True)
    def test_js_hook_execution(self, tmp_path, hermetic_lib_dir):
        """A shipped JavaScript hook should execute through projected Node."""
        from archivebox.services.runner import run_install

        lib_dir = hermetic_lib_dir
        run_install(plugin_names=["chrome"])
        chrome_config = Path(
            str(files("abx_plugins.plugins.chrome").joinpath("config.json")),
        )
        node_env = resolve_abxpkg_binary_env(
            lib_dir,
            deps_from=chrome_config,
        )
        node_binary = lib_dir / "env" / "bin" / "node"
        assert node_binary.is_symlink()

        crawl_dir = tmp_path / "crawl"
        output_dir = crawl_dir / "chrome"
        output_dir.mkdir(parents=True)
        hook_path = Path(
            str(
                files("abx_plugins.plugins.chrome").joinpath(
                    "on_CrawlSetup__89_chrome_kill_zombies.js",
                ),
            ),
        )

        result = subprocess.run(
            [str(node_binary), str(hook_path)],
            cwd=output_dir,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                **node_env,
                "CRAWL_DIR": str(crawl_dir),
                "SNAP_DIR": str(crawl_dir / "snapshot"),
                "CHROME_USER_DATA_DIR": str(output_dir / "profile"),
            },
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        assert "chrome zombies" in result.stdout

    @pytest.mark.django_db(transaction=True)
    def test_real_js_hook_runs_through_abxpkg_shebang(self, tmp_path, hermetic_lib_dir):
        from archivebox.plugins.hooks import run_hook
        from archivebox.services.runner import run_install

        lib_dir = hermetic_lib_dir
        run_install(plugin_names=["chrome"])
        node_env = resolve_abxpkg_binary_env(lib_dir, deps_from=CHROME_CONFIG)
        crawl_dir = tmp_path / "crawl"
        snap_dir = crawl_dir / "snapshot"
        hook_path = Path(str(files("abx_plugins.plugins.chrome").joinpath("on_CrawlSetup__89_chrome_kill_zombies.js")))

        process = run_hook(
            hook_path,
            crawl_dir / "chrome",
            config={
                **node_env,
                "ABXPKG_LIB_DIR": str(lib_dir),
                "CRAWL_DIR": str(crawl_dir),
                "SNAP_DIR": str(snap_dir),
                "CHROME_USER_DATA_DIR": str(crawl_dir / "chrome" / "profile"),
            },
            timeout=30,
        )
        process.refresh_from_db()

        assert process.cmd == [str(hook_path)]
        assert process.exit_code == 0, process.stderr
        assert "chrome zombies" in process.stdout

    def test_hook_receives_cli_args(self, tmp_path):
        """Hook should receive CLI arguments."""
        snap_dir = tmp_path / "snapshot"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("real CLI argument input", encoding="utf-8")
        hook_path = Path(
            str(
                files("abx_plugins.plugins.hashes").joinpath(
                    "on_Snapshot__93_hashes.py",
                ),
            ),
        )

        result = subprocess.run(
            [str(hook_path), "--url=https://example.com/real-hook-argument"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            env={**os.environ, "SNAP_DIR": str(snap_dir)},
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(result.stdout)
        source_hash = hashlib.sha256(b"real CLI argument input").hexdigest()
        assert records == [{"type": "ArchiveResult", "status": "succeeded", "output_str": f"0.0MB {source_hash[:12]}"}]
        hashes = json.loads((output_dir / "hashes.json").read_text())
        assert hashes["files"][0]["hash"] == source_hash


class TestDependencyRecordOutput:
    """Test Binary JSONL emitted by the real CLI and persisted model."""

    @pytest.mark.django_db(transaction=True)
    def test_binary_cli_emits_resolved_dependency_record(self, initialized_archive, hermetic_lib_dir):
        install_real_binary("wget", binproviders="env,apt,brew")
        wget_path = resolve_abxpkg_binary_env(hermetic_lib_dir, deps_from=WGET_CONFIG)["WGET_BINARY"]
        version = subprocess.run([wget_path, "--version"], capture_output=True, text=True, check=True).stdout.split()[2]
        from archivebox.tests.conftest import parse_jsonl_output, run_archivebox_cmd

        result = run_archivebox_cmd(
            ["binary", "create", "--name=wget", f"--abspath={wget_path}", f"--version={version}"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert result.returncode == 0, result.stderr

        data = parse_jsonl_output(result.stdout)[0]
        assert data["type"] == "Binary"
        assert data["name"] == "wget"
        assert data["abspath"] == wget_path
        assert data["version"] == version

        list_result = run_archivebox_cmd(
            ["binary", "list", "--name=wget"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert list_result.returncode == 0, list_result.stderr
        listed = parse_jsonl_output(list_result.stdout)
        assert any(record["id"] == data["id"] and record["abspath"] == wget_path for record in listed)


class TestSnapshotHookOutput:
    """Test ArchiveResult records emitted by a shipped snapshot hook."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        ("enabled", "expected_status"),
        [(True, "succeeded"), (False, "skipped")],
    )
    def test_hashes_hook_emits_real_archive_result(self, tmp_path, enabled, expected_status):
        from archivebox.plugins.hooks import extract_records_from_process, run_hook

        snap_dir = tmp_path / f"snapshot-{expected_status}"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("real hook protocol input", encoding="utf-8")
        hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))

        process = run_hook(
            hook_path,
            output_dir,
            config={
                "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
                "SNAP_DIR": str(snap_dir),
                "HASHES_ENABLED": enabled,
            },
            timeout=30,
            url="https://example.com/real-hook-record",
        )
        process.refresh_from_db()

        assert process.exit_code == 0, process.stderr
        records = extract_records_from_process(process)
        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == expected_status
        assert records[0]["plugin"] == "hashes"
        assert records[0]["hook_name"] == hook_path.name
        assert records[0]["plugin_hook"] == str(hook_path)
        if enabled:
            assert (output_dir / "hashes.json").is_file()
        else:
            assert records[0]["output_str"] == "HASHES_ENABLED=False"


class TestPluginMetadata:
    """Test that plugin metadata is added to JSONL records."""

    @pytest.mark.django_db(transaction=True)
    def test_python_hook_metadata_comes_from_executed_shipped_hook(self, tmp_path):
        from archivebox.plugins.hooks import extract_records_from_process, run_hook

        snap_dir = tmp_path / "snapshot-metadata"
        output_dir = snap_dir / "hashes"
        output_dir.mkdir(parents=True)
        (snap_dir / "source.txt").write_text("metadata", encoding="utf-8")
        script = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
        process = run_hook(
            script,
            output_dir,
            config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
            timeout=30,
            url="https://example.com/metadata",
        )
        process.refresh_from_db()

        assert process.exit_code == 0, process.stderr
        records = extract_records_from_process(process)
        assert records[0]["plugin"] == "hashes"
        assert records[0]["hook_name"] == script.name
        assert records[0]["plugin_hook"] == str(script)


@pytest.mark.django_db(transaction=True)
def test_run_hook_exports_singular_node_modules_dir_with_colon_node_path(tmp_path, hermetic_lib_dir):
    """Hook subprocesses must get a real NODE_MODULES_DIR even when NODE_PATH has multiple entries."""
    from archivebox.plugins.hooks import run_hook
    from archivebox.services.runner import run_install

    lib_dir = hermetic_lib_dir
    run_install(plugin_names=["chrome"])
    chrome_config = Path(str(files("abx_plugins.plugins.chrome").joinpath("config.json")))
    node_env = resolve_abxpkg_binary_env(
        lib_dir,
        deps_from=chrome_config,
    )
    configured_node_path = node_env["NODE_PATH"]
    node_modules_dir = Path(node_env["NODE_MODULES_DIR"])
    crawl_dir = tmp_path / "crawl"
    output_dir = crawl_dir / "chrome"
    hook_path = Path(str(files("abx_plugins.plugins.chrome").joinpath("on_CrawlSetup__89_chrome_kill_zombies.js")))
    process = run_hook(
        hook_path,
        output_dir,
        config={
            **node_env,
            "ABXPKG_LIB_DIR": str(lib_dir),
            "CRAWL_DIR": str(crawl_dir),
            "SNAP_DIR": str(crawl_dir / "snapshot"),
            "CHROME_USER_DATA_DIR": str(output_dir / "profile"),
        },
        timeout=30,
    )
    process.refresh_from_db()

    assert process.exit_code == 0, process.stderr
    assert process.env["NODE_MODULES_DIR"] == str(node_modules_dir)
    assert process.env["NODE_MODULE_DIR"] == str(node_modules_dir)
    assert process.env["NODE_PATH"].split(os.pathsep) == configured_node_path.split(os.pathsep)
    assert "chrome zombies" in process.stdout


@pytest.mark.django_db(transaction=True)
def test_run_hook_executes_python_hooks_through_abxpkg_shebang(tmp_path):
    """ArchiveBox treats Python hooks as opaque abxpkg-launched executables."""
    from archivebox.plugins.hooks import run_hook

    snap_dir = tmp_path / "snapshot"
    output_dir = snap_dir / "hashes"
    output_dir.mkdir(parents=True)
    (snap_dir / "source.txt").write_text("real runtime hook input", encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
    process = run_hook(
        hook_path,
        output_dir,
        config={
            "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
            "SNAP_DIR": str(snap_dir),
        },
        timeout=30,
        url="https://example.com/runtime",
    )
    process.refresh_from_db()

    assert process.cmd == [str(hook_path), "--url=https://example.com/runtime"]
    assert process.exit_code == 0, process.stderr
    assert process.env["SNAP_DIR"] == str(snap_dir)
    records = process.parse_records_from_text(process.stdout)
    source_hash = hashlib.sha256(b"real runtime hook input").hexdigest()
    assert records == [{"type": "ArchiveResult", "status": "succeeded", "output_str": f"0.0MB {source_hash[:12]}"}]
    hashes = json.loads((output_dir / "hashes.json").read_text())
    source = hashes["files"][0]
    assert source["path"] == "source.txt"
    assert source["size"] == len("real runtime hook input")
    assert source["hash"] == source_hash
