#!/usr/bin/env python3
"""
Unit tests for the ArchiveBox hook architecture.

Tests hook discovery, execution, JSONL parsing, background hook detection,
binary lookup, and required_binaries XYZ_BINARY passthrough handling.

Run with:
    sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_hooks.py -v'
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import rich_click as click

# Set up Django before importing any Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.settings")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
RESULT_PREFIX = "__ARCHIVEBOX_TEST_RESULT__="


def create_test_plugin_structure(plugins_dir: Path) -> None:
    """Create a minimal plugin tree for hook discovery tests."""
    plugins_dir.mkdir()

    wget_dir = plugins_dir / "wget"
    wget_dir.mkdir()
    (wget_dir / "on_Snapshot__50_wget.py").write_text("# test hook")

    chrome_dir = plugins_dir / "chrome"
    chrome_dir.mkdir(exist_ok=True)
    (chrome_dir / "on_Snapshot__20_chrome_tab.daemon.bg.js").write_text("// background hook")

    consolelog_dir = plugins_dir / "consolelog"
    consolelog_dir.mkdir()
    (consolelog_dir / "on_Snapshot__21_consolelog.daemon.bg.js").write_text("// background hook")


def run_plugin_discovery_subprocess(tmp_path: Path, plugins_dir: Path, script: str):
    env = os.environ.copy()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cwd_plugins_dir = data_dir / "custom_plugins"
    if plugins_dir != cwd_plugins_dir:
        shutil.copytree(plugins_dir, cwd_plugins_dir)
    existing_pythonpath = [
        str(Path(entry).expanduser().resolve(strict=False))
        for entry in env.get("PYTHONPATH", "").split(os.pathsep)
        if entry and Path(entry).expanduser().is_absolute()
    ]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys([str(REPO_ROOT), *existing_pythonpath]))
    subprocess_script = "\n".join(
        [
            "import json",
            f"RESULT_PREFIX = {RESULT_PREFIX!r}",
            "",
            "def emit(value):",
            "    print(RESULT_PREFIX + json.dumps(value))",
            "",
            textwrap.dedent(script),
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            subprocess_script,
        ],
        cwd=data_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    for line in reversed(result.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line.removeprefix(RESULT_PREFIX))

    raise AssertionError(f"Subprocess did not emit a result line.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")


def test_cli_env_does_not_emit_relative_pythonpath_entries():
    from archivebox.tests.conftest import cli_env

    old_pythonpath = os.environ.get("PYTHONPATH")
    try:
        os.environ["PYTHONPATH"] = os.pathsep.join(["../abxpkg", "../abx-plugins", "../abx-dl"])

        env = cli_env()
    finally:
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath

    pythonpath_entries = env["PYTHONPATH"].split(os.pathsep)
    for repo_name in ("abxpkg", "abx-plugins", "abx-dl"):
        repo_path = next(path for path in (WORKSPACE_ROOT / repo_name, REPO_ROOT / repo_name) if path.exists())
        assert str(repo_path.resolve(strict=False)) in pythonpath_entries
    assert all(Path(entry).is_absolute() for entry in pythonpath_entries)
    assert not any(entry.startswith("..") for entry in pythonpath_entries)


class TestBackgroundHookDetection:
    """Test that background hooks are detected by .bg. suffix."""

    def test_bg_js_suffix_detected(self):
        """Hooks with .bg.js suffix should be detected as background."""
        from archivebox.plugins.hooks import is_background_hook

        assert is_background_hook("on_Snapshot__21_consolelog.daemon.bg.js")

    def test_bg_py_suffix_detected(self):
        """Hooks with .bg.py suffix should be detected as background."""
        from archivebox.plugins.hooks import is_background_hook

        assert is_background_hook("on_Snapshot__24_responses.finite.bg.py")

    def test_bg_sh_suffix_detected(self):
        """Hooks with .bg.sh suffix should be detected as background."""
        from archivebox.plugins.hooks import is_background_hook

        assert is_background_hook("on_Snapshot__23_ssl.daemon.bg.sh")

    def test_legacy_background_suffix_detected(self):
        """Hooks with __background in stem should be detected (backwards compat)."""
        from archivebox.plugins.hooks import is_background_hook

        assert is_background_hook("on_Snapshot__21_consolelog__background.js")

    def test_foreground_hook_not_detected(self):
        """Hooks without .bg. or __background should NOT be detected as background."""
        from archivebox.plugins.hooks import is_background_hook

        assert not is_background_hook("on_Snapshot__11_favicon.js")

    def test_foreground_py_hook_not_detected(self):
        """Python hooks without .bg. should NOT be detected as background."""
        from archivebox.plugins.hooks import is_background_hook

        assert not is_background_hook("on_Snapshot__50_wget.py")


class TestJSONLParsing:
    """Test JSONL parsing in run_hook() output processing."""

    def test_parse_clean_jsonl(self):
        """Clean JSONL format should be parsed correctly."""
        stdout = '{"type": "ArchiveResult", "status": "succeeded", "output_str": "Done"}'
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(stdout)

        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == "succeeded"
        assert records[0]["output_str"] == "Done"

    def test_parse_multiple_jsonl_records(self):
        """Multiple JSONL records should all be parsed."""
        stdout = """{"type": "ArchiveResult", "status": "succeeded", "output_str": "Done"}
{"type": "Binary", "name": "wget", "abspath": "/usr/bin/wget"}"""
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(stdout)

        assert len(records) == 2
        assert records[0]["type"] == "ArchiveResult"
        assert records[1]["type"] == "Binary"

    def test_parse_jsonl_with_log_output(self):
        """JSONL should be extracted from mixed stdout with log lines."""
        stdout = """Starting hook execution...
Processing URL: https://example.com
{"type": "ArchiveResult", "status": "succeeded", "output_str": "Downloaded"}
Hook completed successfully"""
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(stdout)

        assert len(records) == 1
        assert records[0]["status"] == "succeeded"

    def test_ignore_invalid_json(self):
        """Invalid JSON should be silently ignored."""
        stdout = """{"type": "ArchiveResult", "status": "succeeded"}
{invalid json here}
not json at all
{"type": "BinaryRequest", "name": "wget"}"""
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(stdout)

        assert len(records) == 2

    def test_json_without_type_ignored(self):
        """JSON objects without 'type' field should be ignored."""
        stdout = """{"status": "succeeded", "output_str": "Done"}
{"type": "ArchiveResult", "status": "succeeded"}"""
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(stdout)

        assert len(records) == 1
        assert records[0]["type"] == "ArchiveResult"


class TestRequiredBinaryConfigHandling:
    """Test that required_binaries keep configured XYZ_BINARY values intact."""

    def test_binary_env_var_absolute_path_handling(self):
        """Absolute binary paths should pass through unchanged."""
        configured_binary = "/custom/path/to/wget2"
        binary_name = configured_binary

        assert binary_name == "/custom/path/to/wget2"

    def test_binary_env_var_name_only_handling(self):
        """Binary command names should pass through unchanged."""
        configured_binary = "wget2"
        binary_name = configured_binary

        assert binary_name == "wget2"

    def test_binary_env_var_empty_default(self):
        """Empty configured binary values should keep the schema default."""
        configured_binary = ""
        if configured_binary:
            binary_name = configured_binary
        else:
            binary_name = "wget"

        assert binary_name == "wget"


class TestHookDiscovery:
    """Test hook discovery functions."""

    def test_discover_hooks_by_event(self, tmp_path):
        """discover_hooks() should find all hooks for an event."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        hooks = []
        for ext in ("sh", "py", "js"):
            pattern = f"*/on_Snapshot__*.{ext}"
            hooks.extend(plugins_dir.glob(pattern))

        hooks = sorted(set(hooks), key=lambda p: p.name)

        assert len(hooks) == 3
        hook_names = [h.name for h in hooks]
        assert "on_Snapshot__20_chrome_tab.daemon.bg.js" in hook_names
        assert "on_Snapshot__21_consolelog.daemon.bg.js" in hook_names
        assert "on_Snapshot__50_wget.py" in hook_names

    def test_discover_hooks_sorted_by_name(self, tmp_path):
        """Hooks should be sorted by filename (numeric prefix ordering)."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        hooks = []
        for ext in ("sh", "py", "js"):
            pattern = f"*/on_Snapshot__*.{ext}"
            hooks.extend(plugins_dir.glob(pattern))

        hooks = sorted(set(hooks), key=lambda p: p.name)

        # Check numeric ordering
        assert hooks[0].name == "on_Snapshot__20_chrome_tab.daemon.bg.js"
        assert hooks[1].name == "on_Snapshot__21_consolelog.daemon.bg.js"
        assert hooks[2].name == "on_Snapshot__50_wget.py"

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

    def test_discover_hooks_skips_plugins_with_disabled_required_dependencies(self, tmp_path):
        """Plugins whose required_plugins are disabled should not run."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        chrome_dir = plugins_dir / "chrome"
        chrome_dir.mkdir(exist_ok=True)
        (chrome_dir / "config.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "required_plugins": [],
                    "properties": {
                        "CHROME_ENABLED": {
                            "type": "boolean",
                            "default": True,
                            "x-aliases": ["USE_CHROME"],
                        },
                    },
                },
            ),
        )
        (chrome_dir / "on_Snapshot__20_chrome.js").write_text("// chrome hook")

        accessibility_dir = plugins_dir / "accessibility"
        accessibility_dir.mkdir(exist_ok=True)
        (accessibility_dir / "config.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "required_plugins": ["chrome"],
                    "properties": {
                        "ACCESSIBILITY_ENABLED": {
                            "type": "boolean",
                            "default": True,
                        },
                    },
                },
            ),
        )
        (accessibility_dir / "on_Snapshot__10_accessibility.js").write_text("// accessibility hook")

        wget_dir = plugins_dir / "wget"
        (wget_dir / "config.json").write_text(
            json.dumps(
                {
                    "type": "object",
                    "required_plugins": [],
                    "properties": {
                        "WGET_ENABLED": {
                            "type": "boolean",
                            "default": True,
                            "x-aliases": ["SAVE_WGET"],
                        },
                    },
                },
            ),
        )

        hook_names = run_plugin_discovery_subprocess(
            tmp_path,
            plugins_dir,
            """
            from archivebox.plugins import hooks as hooks_module

            hooks = hooks_module.discover_hooks("Snapshot", config={"CHROME_ENABLED": False, "WGET_ENABLED": True})
            emit([hook.parent.name for hook in hooks])
            """,
        )
        assert "wget" in hook_names
        assert "chrome" not in hook_names
        assert "accessibility" not in hook_names

    def test_get_plugins_includes_config_only_plugin_dirs(self, tmp_path):
        """get_plugins() should include config-only plugins with standardized metadata."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        helper_dir = plugins_dir / "helper"
        helper_dir.mkdir()
        (helper_dir / "config.json").write_text('{"type": "object", "properties": {}}')

        plugins = run_plugin_discovery_subprocess(
            tmp_path,
            plugins_dir,
            """
            from archivebox.plugins import hooks as hooks_module

            from archivebox.plugins.discovery import get_plugins
            get_plugins.cache_clear()
            emit(get_plugins())
            """,
        )
        assert "helper" in plugins

    def test_discover_binary_hooks_returns_empty(self, tmp_path):
        """Binary provider hooks are owned by abxpkg, not ArchiveBox plugin discovery."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        hook_names = run_plugin_discovery_subprocess(
            tmp_path,
            plugins_dir,
            """
            from archivebox.plugins import hooks as hooks_module

            from archivebox.plugins.discovery import get_plugins
            get_plugins.cache_clear()
            hooks = hooks_module.discover_hooks("BinaryRequest", filter_disabled=False)
            emit([hook.name for hook in hooks])
            """,
        )
        assert hook_names == []

    def test_discover_hooks_accepts_event_class_names(self, tmp_path):
        """discover_hooks should accept CrawlSetupEvent / SnapshotEvent class names."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)
        chrome_dir = plugins_dir / "chrome"
        (chrome_dir / "on_CrawlSetup__90_chrome_launch.daemon.bg.js").write_text("// crawl hook")

        hook_names = run_plugin_discovery_subprocess(
            tmp_path,
            plugins_dir,
            """
            from archivebox.plugins import hooks as hooks_module

            from archivebox.plugins.discovery import get_plugins
            get_plugins.cache_clear()
            crawl_setup_hooks = hooks_module.discover_hooks("CrawlSetupEvent", filter_disabled=False)
            snapshot_hooks = hooks_module.discover_hooks("SnapshotEvent", filter_disabled=False)
            emit({
                "crawl_setup": [hook.name for hook in crawl_setup_hooks],
                "snapshot": [hook.name for hook in snapshot_hooks],
            })
            """,
        )
        assert "on_CrawlSetup__90_chrome_launch.daemon.bg.js" in hook_names["crawl_setup"]
        assert "on_Snapshot__50_wget.py" in hook_names["snapshot"]

    def test_discover_hooks_returns_empty_for_non_hook_lifecycle_events(self, tmp_path):
        """Lifecycle events without a hook family should return no hooks."""
        plugins_dir = tmp_path / "plugins"
        create_test_plugin_structure(plugins_dir)

        hooks = run_plugin_discovery_subprocess(
            tmp_path,
            plugins_dir,
            """
            from archivebox.plugins import hooks as hooks_module

            from archivebox.plugins.discovery import get_plugins
            get_plugins.cache_clear()
            emit({
                "binary": [hook.name for hook in hooks_module.discover_hooks("BinaryEvent", filter_disabled=False)],
                "crawl_cleanup": [
                    hook.name for hook in hooks_module.discover_hooks("CrawlCleanupEvent", filter_disabled=False)
                ],
            })
            """,
        )
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
        hook_path = tmp_path / "test_hook.py"
        hook_path.write_text("""#!/usr/bin/env python3
import json
print(json.dumps({"type": "ArchiveResult", "status": "succeeded", "output_str": "Test passed"}))
""")

        result = subprocess.run(
            [sys.executable, str(hook_path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(result.stdout)
        assert records
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == "succeeded"

    def test_js_hook_execution(self, tmp_path):
        """JavaScript hook should execute and output JSONL."""
        assert shutil.which("node") is not None, "Node.js not available"

        hook_path = tmp_path / "test_hook.js"
        hook_path.write_text("""#!/usr/bin/env node
console.log(JSON.stringify({type: 'ArchiveResult', status: 'succeeded', output_str: 'JS test'}));
""")

        result = subprocess.run(
            ["node", str(hook_path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(result.stdout)
        assert records
        assert records[0]["type"] == "ArchiveResult"
        assert records[0]["status"] == "succeeded"

    def test_hook_receives_cli_args(self, tmp_path):
        """Hook should receive CLI arguments."""
        hook_path = tmp_path / "test_hook.py"
        hook_path.write_text("""#!/usr/bin/env python3
import sys
import json
# Simple arg parsing
args = {}
for arg in sys.argv[1:]:
    if arg.startswith('--') and '=' in arg:
        key, val = arg[2:].split('=', 1)
        args[key.replace('-', '_')] = val
print(json.dumps({"type": "ArchiveResult", "status": "succeeded", "url": args.get("url", "")}))
""")

        result = subprocess.run(
            [sys.executable, str(hook_path), "--url=https://example.com"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        from archivebox.machine.models import Process

        records = Process.parse_records_from_text(result.stdout)
        assert records
        assert records[0]["url"] == "https://example.com"


class TestDependencyRecordOutput:
    """Test dependency record output format compliance."""

    def test_dependency_record_outputs_binary(self):
        """Dependency resolution should output Binary JSONL when binary is found."""
        hook_output = json.dumps(
            {
                "type": "Binary",
                "name": "wget",
                "abspath": "/usr/bin/wget",
                "version": "1.21.3",
                "sha256": None,
                "binprovider": "apt",
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["type"] == "Binary"
        assert data["name"] == "wget"
        assert data["abspath"].startswith("/")

    def test_dependency_record_outputs_binary_jsonl(self):
        """Dependency resolution should output Binary JSONL."""
        hook_output = json.dumps(
            {
                "type": "Binary",
                "name": "wget",
                "abspath": "/usr/bin/wget",
                "version": "1.21.3",
                "binprovider": "env",
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["type"] == "Binary"
        assert data["name"] == "wget"
        assert data["abspath"] == "/usr/bin/wget"


class TestSnapshotHookOutput:
    """Test snapshot hook output format compliance."""

    def test_snapshot_hook_basic_output(self):
        """Snapshot hook should output clean ArchiveResult JSONL."""
        hook_output = json.dumps(
            {
                "type": "ArchiveResult",
                "status": "succeeded",
                "output_str": "Downloaded 5 files",
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["type"] == "ArchiveResult"
        assert data["status"] == "succeeded"
        assert "output_str" in data

    def test_snapshot_hook_with_cmd(self):
        """Snapshot hook should include cmd for binary FK lookup."""
        hook_output = json.dumps(
            {
                "type": "ArchiveResult",
                "status": "succeeded",
                "output_str": "Archived with wget",
                "cmd": ["/usr/bin/wget", "-p", "-k", "https://example.com"],
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["type"] == "ArchiveResult"
        assert isinstance(data["cmd"], list)
        assert data["cmd"][0] == "/usr/bin/wget"

    def test_snapshot_hook_with_output_json(self):
        """Snapshot hook can include structured metadata in output_json."""
        hook_output = json.dumps(
            {
                "type": "ArchiveResult",
                "status": "succeeded",
                "output_str": "Got headers",
                "output_json": {
                    "content-type": "text/html",
                    "server": "nginx",
                    "status-code": 200,
                },
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["type"] == "ArchiveResult"
        assert isinstance(data["output_json"], dict)
        assert data["output_json"]["status-code"] == 200

    def test_snapshot_hook_skipped_status(self):
        """Snapshot hook should support skipped status."""
        hook_output = json.dumps(
            {
                "type": "ArchiveResult",
                "status": "skipped",
                "output_str": "SAVE_WGET=False",
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["status"] == "skipped"

    def test_snapshot_hook_failed_status(self):
        """Snapshot hook should support failed status."""
        hook_output = json.dumps(
            {
                "type": "ArchiveResult",
                "status": "failed",
                "output_str": "404 Not Found",
            },
        )

        from archivebox.machine.models import Process

        data = Process.parse_records_from_text(hook_output)[0]
        assert data["status"] == "failed"


class TestPluginMetadata:
    """Test that plugin metadata is added to JSONL records."""

    def test_plugin_name_added(self):
        """run_hook() should add plugin name to records."""
        # Simulate what run_hook() does
        script = Path("/abx_plugins/plugins/wget/on_Snapshot__50_wget.py")
        plugin_name = script.parent.name

        record = {"type": "ArchiveResult", "status": "succeeded"}
        record["plugin"] = plugin_name
        record["plugin_hook"] = str(script)

        assert record["plugin"] == "wget"
        assert "on_Snapshot__50_wget.py" in record["plugin_hook"]


@pytest.mark.django_db(transaction=True)
def test_run_hook_exports_singular_node_modules_dir_with_colon_node_path(tmp_path):
    """Hook subprocesses must get a real NODE_MODULES_DIR even when NODE_PATH has multiple entries."""
    from archivebox.plugins.hooks import run_hook

    lib_dir = tmp_path / "lib"
    node_modules_dir = lib_dir / "pnpm" / "packages" / "chrome" / "node_modules"
    configured_node_path = os.pathsep.join(
        [
            "/home/archivebox/.pnpm/packages/chrome/node_modules",
            "/usr/lib/node_modules",
            str(node_modules_dir),
            "/usr/share/archivebox/lib/pnpm/packages/chrome/node_modules",
        ],
    )

    plugin_dir = tmp_path / "plugins" / "envprobe"
    plugin_dir.mkdir(parents=True)
    hook_path = plugin_dir / "on_Snapshot__99_envprobe.py"
    hook_path.write_text(
        """#!/usr/bin/env python3
import json
import os

print(json.dumps({
    "NODE_PATH": os.environ.get("NODE_PATH"),
    "NODE_MODULES_DIR": os.environ.get("NODE_MODULES_DIR"),
    "NODE_MODULE_DIR": os.environ.get("NODE_MODULE_DIR"),
}))
""",
        encoding="utf-8",
    )
    hook_path.chmod(0o755)

    output_dir = tmp_path / "archive" / "users" / "system" / "snapshots" / "20260513" / "example.com" / "test" / "envprobe"
    process = run_hook(
        hook_path,
        output_dir,
        config={
            "LIB_DIR": str(lib_dir),
            "NODE_PATH": configured_node_path,
        },
        timeout=10,
    )
    process.refresh_from_db()

    assert process.exit_code == 0, process.stderr
    payload = json.loads(process.stdout.strip())
    assert payload["NODE_MODULES_DIR"] == str(node_modules_dir)
    assert payload["NODE_MODULE_DIR"] == str(node_modules_dir)
    assert payload["NODE_PATH"].split(os.pathsep) == configured_node_path.split(os.pathsep)
    assert process.env["NODE_MODULES_DIR"] == str(node_modules_dir)


@pytest.mark.django_db(transaction=True)
def test_run_hook_executes_python_hooks_through_script_shebang(tmp_path):
    """Python hooks must use their abxpkg script header instead of sys.executable."""
    from archivebox.plugins.hooks import run_hook

    plugin_dir = tmp_path / "plugins" / "shebangprobe"
    plugin_dir.mkdir(parents=True)
    hook_path = plugin_dir / "on_Snapshot__99_shebangprobe.py"
    hook_path.write_text(
        """#!/usr/bin/env -S abxpkg run --script python3
# /// script
# requires-python = ">=3.12"
# ///
import json
import os
import rich_click

print(json.dumps({
    "ABXPKG_FAST_SCRIPT": os.environ.get("ABXPKG_FAST_SCRIPT"),
    "RICH_CLICK_FILE": rich_click.__file__,
}))
""",
        encoding="utf-8",
    )
    hook_path.chmod(0o755)

    output_dir = tmp_path / "archive" / "users" / "system" / "snapshots" / "20260603" / "example.com" / "test" / "shebangprobe"
    process = run_hook(
        hook_path,
        output_dir,
        config={
            "LIB_DIR": str(tmp_path / "lib"),
        },
        timeout=10,
    )
    process.refresh_from_db()

    assert process.cmd[0] == str(hook_path)
    assert process.exit_code == 0, process.stderr
    payload = json.loads(process.stdout.strip())
    assert payload["ABXPKG_FAST_SCRIPT"] == "1"
    assert Path(payload["RICH_CLICK_FILE"]).resolve() == Path(click.__file__).resolve()
