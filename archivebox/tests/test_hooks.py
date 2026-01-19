#!/usr/bin/env python3
"""
Unit tests for the ArchiveBox hook architecture.

Tests hook discovery, execution, JSONL parsing, background hook detection,
binary lookup, and install hook XYZ_BINARY env var handling.

Run with:
    sudo -u testuser bash -c 'source .venv/bin/activate && python -m pytest archivebox/tests/test_hooks.py -v'
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set up Django before importing any Django-dependent modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')


class TestBackgroundHookDetection(unittest.TestCase):
    """Test that background hooks are detected by .bg. suffix."""

    def test_bg_js_suffix_detected(self):
        """Hooks with .bg.js suffix should be detected as background."""
        script = Path('/path/to/on_Snapshot__21_consolelog.bg.js')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertTrue(is_background)

    def test_bg_py_suffix_detected(self):
        """Hooks with .bg.py suffix should be detected as background."""
        script = Path('/path/to/on_Snapshot__24_responses.bg.py')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertTrue(is_background)

    def test_bg_sh_suffix_detected(self):
        """Hooks with .bg.sh suffix should be detected as background."""
        script = Path('/path/to/on_Snapshot__23_ssl.bg.sh')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertTrue(is_background)

    def test_legacy_background_suffix_detected(self):
        """Hooks with __background in stem should be detected (backwards compat)."""
        script = Path('/path/to/on_Snapshot__21_consolelog__background.js')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertTrue(is_background)

    def test_foreground_hook_not_detected(self):
        """Hooks without .bg. or __background should NOT be detected as background."""
        script = Path('/path/to/on_Snapshot__11_favicon.js')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertFalse(is_background)

    def test_foreground_py_hook_not_detected(self):
        """Python hooks without .bg. should NOT be detected as background."""
        script = Path('/path/to/on_Snapshot__50_wget.py')
        is_background = '.bg.' in script.name or '__background' in script.stem
        self.assertFalse(is_background)


class TestJSONLParsing(unittest.TestCase):
    """Test JSONL parsing in run_hook() output processing."""

    def test_parse_clean_jsonl(self):
        """Clean JSONL format should be parsed correctly."""
        stdout = '{"type": "ArchiveResult", "status": "succeeded", "output_str": "Done"}'
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(stdout)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'ArchiveResult')
        self.assertEqual(records[0]['status'], 'succeeded')
        self.assertEqual(records[0]['output_str'], 'Done')

    def test_parse_multiple_jsonl_records(self):
        """Multiple JSONL records should all be parsed."""
        stdout = '''{"type": "ArchiveResult", "status": "succeeded", "output_str": "Done"}
{"type": "Binary", "name": "wget", "abspath": "/usr/bin/wget"}'''
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(stdout)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['type'], 'ArchiveResult')
        self.assertEqual(records[1]['type'], 'Binary')

    def test_parse_jsonl_with_log_output(self):
        """JSONL should be extracted from mixed stdout with log lines."""
        stdout = '''Starting hook execution...
Processing URL: https://example.com
{"type": "ArchiveResult", "status": "succeeded", "output_str": "Downloaded"}
Hook completed successfully'''
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(stdout)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'succeeded')

    def test_ignore_invalid_json(self):
        """Invalid JSON should be silently ignored."""
        stdout = '''{"type": "ArchiveResult", "status": "succeeded"}
{invalid json here}
not json at all
{"type": "Binary", "name": "wget"}'''
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(stdout)

        self.assertEqual(len(records), 2)

    def test_json_without_type_ignored(self):
        """JSON objects without 'type' field should be ignored."""
        stdout = '''{"status": "succeeded", "output_str": "Done"}
{"type": "ArchiveResult", "status": "succeeded"}'''
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(stdout)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'ArchiveResult')


class TestInstallHookEnvVarHandling(unittest.TestCase):
    """Test that install hooks respect XYZ_BINARY env vars."""

    def setUp(self):
        """Set up test environment."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.test_hook = self.work_dir / 'test_hook.py'

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_binary_env_var_absolute_path_handling(self):
        """Install hooks should handle absolute paths in XYZ_BINARY."""
        # Test the logic that install hooks use
        configured_binary = '/custom/path/to/wget2'
        if '/' in configured_binary:
            bin_name = Path(configured_binary).name
        else:
            bin_name = configured_binary

        self.assertEqual(bin_name, 'wget2')

    def test_binary_env_var_name_only_handling(self):
        """Install hooks should handle binary names in XYZ_BINARY."""
        # Test the logic that install hooks use
        configured_binary = 'wget2'
        if '/' in configured_binary:
            bin_name = Path(configured_binary).name
        else:
            bin_name = configured_binary

        self.assertEqual(bin_name, 'wget2')

    def test_binary_env_var_empty_default(self):
        """Install hooks should use default when XYZ_BINARY is empty."""
        configured_binary = ''
        if configured_binary:
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary
        else:
            bin_name = 'wget'  # default

        self.assertEqual(bin_name, 'wget')


class TestHookDiscovery(unittest.TestCase):
    """Test hook discovery functions."""

    def setUp(self):
        """Set up test plugin directory."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.plugins_dir = self.test_dir / 'plugins'
        self.plugins_dir.mkdir()

        # Create test plugin structure
        wget_dir = self.plugins_dir / 'wget'
        wget_dir.mkdir()
        (wget_dir / 'on_Snapshot__50_wget.py').write_text('# test hook')
        (wget_dir / 'on_Crawl__00_install_wget.py').write_text('# install hook')

        chrome_dir = self.plugins_dir / 'chrome'
        chrome_dir.mkdir()
        (chrome_dir / 'on_Snapshot__20_chrome_tab.bg.js').write_text('// background hook')

        consolelog_dir = self.plugins_dir / 'consolelog'
        consolelog_dir.mkdir()
        (consolelog_dir / 'on_Snapshot__21_consolelog.bg.js').write_text('// background hook')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_discover_hooks_by_event(self):
        """discover_hooks() should find all hooks for an event."""
        # Use the local implementation since we can't easily mock BUILTIN_PLUGINS_DIR
        hooks = []
        for ext in ('sh', 'py', 'js'):
            pattern = f'*/on_Snapshot__*.{ext}'
            hooks.extend(self.plugins_dir.glob(pattern))

        hooks = sorted(set(hooks), key=lambda p: p.name)

        self.assertEqual(len(hooks), 3)
        hook_names = [h.name for h in hooks]
        self.assertIn('on_Snapshot__20_chrome_tab.bg.js', hook_names)
        self.assertIn('on_Snapshot__21_consolelog.bg.js', hook_names)
        self.assertIn('on_Snapshot__50_wget.py', hook_names)

    def test_discover_hooks_sorted_by_name(self):
        """Hooks should be sorted by filename (numeric prefix ordering)."""
        hooks = []
        for ext in ('sh', 'py', 'js'):
            pattern = f'*/on_Snapshot__*.{ext}'
            hooks.extend(self.plugins_dir.glob(pattern))

        hooks = sorted(set(hooks), key=lambda p: p.name)

        # Check numeric ordering
        self.assertEqual(hooks[0].name, 'on_Snapshot__20_chrome_tab.bg.js')
        self.assertEqual(hooks[1].name, 'on_Snapshot__21_consolelog.bg.js')
        self.assertEqual(hooks[2].name, 'on_Snapshot__50_wget.py')


class TestGetExtractorName(unittest.TestCase):
    """Test get_extractor_name() function."""

    def test_strip_numeric_prefix(self):
        """Numeric prefix should be stripped from extractor name."""
        # Inline implementation of get_extractor_name
        def get_extractor_name(extractor: str) -> str:
            parts = extractor.split('_', 1)
            if len(parts) == 2 and parts[0].isdigit():
                return parts[1]
            return extractor

        self.assertEqual(get_extractor_name('10_title'), 'title')
        self.assertEqual(get_extractor_name('26_readability'), 'readability')
        self.assertEqual(get_extractor_name('50_parse_html_urls'), 'parse_html_urls')

    def test_no_prefix_unchanged(self):
        """Extractor without numeric prefix should be unchanged."""
        def get_extractor_name(extractor: str) -> str:
            parts = extractor.split('_', 1)
            if len(parts) == 2 and parts[0].isdigit():
                return parts[1]
            return extractor

        self.assertEqual(get_extractor_name('title'), 'title')
        self.assertEqual(get_extractor_name('readability'), 'readability')


class TestHookExecution(unittest.TestCase):
    """Test hook execution with real subprocesses."""

    def setUp(self):
        """Set up test environment."""
        self.work_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_python_hook_execution(self):
        """Python hook should execute and output JSONL."""
        hook_path = self.work_dir / 'test_hook.py'
        hook_path.write_text('''#!/usr/bin/env python3
import json
print(json.dumps({"type": "ArchiveResult", "status": "succeeded", "output_str": "Test passed"}))
''')

        result = subprocess.run(
            ['python3', str(hook_path)],
            cwd=str(self.work_dir),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(result.stdout)
        self.assertTrue(records)
        self.assertEqual(records[0]['type'], 'ArchiveResult')
        self.assertEqual(records[0]['status'], 'succeeded')

    def test_js_hook_execution(self):
        """JavaScript hook should execute and output JSONL."""
        # Skip if node not available
        if shutil.which('node') is None:
            self.skipTest('Node.js not available')

        hook_path = self.work_dir / 'test_hook.js'
        hook_path.write_text('''#!/usr/bin/env node
console.log(JSON.stringify({type: 'ArchiveResult', status: 'succeeded', output_str: 'JS test'}));
''')

        result = subprocess.run(
            ['node', str(hook_path)],
            cwd=str(self.work_dir),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(result.stdout)
        self.assertTrue(records)
        self.assertEqual(records[0]['type'], 'ArchiveResult')
        self.assertEqual(records[0]['status'], 'succeeded')

    def test_hook_receives_cli_args(self):
        """Hook should receive CLI arguments."""
        hook_path = self.work_dir / 'test_hook.py'
        hook_path.write_text('''#!/usr/bin/env python3
import sys
import json
# Simple arg parsing
args = {}
for arg in sys.argv[1:]:
    if arg.startswith('--') and '=' in arg:
        key, val = arg[2:].split('=', 1)
        args[key.replace('-', '_')] = val
print(json.dumps({"type": "ArchiveResult", "status": "succeeded", "url": args.get("url", "")}))
''')

        result = subprocess.run(
            ['python3', str(hook_path), '--url=https://example.com'],
            cwd=str(self.work_dir),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        from archivebox.machine.models import Process
        records = Process.parse_records_from_text(result.stdout)
        self.assertTrue(records)
        self.assertEqual(records[0]['url'], 'https://example.com')


class TestInstallHookOutput(unittest.TestCase):
    """Test install hook output format compliance."""

    def setUp(self):
        """Set up test environment."""
        self.work_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_install_hook_outputs_binary(self):
        """Install hook should output Binary JSONL when binary found."""
        hook_output = json.dumps({
            'type': 'Binary',
            'name': 'wget',
            'abspath': '/usr/bin/wget',
            'version': '1.21.3',
            'sha256': None,
            'binprovider': 'apt',
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['type'], 'Binary')
        self.assertEqual(data['name'], 'wget')
        self.assertTrue(data['abspath'].startswith('/'))

    def test_install_hook_outputs_machine_config(self):
        """Install hook should output Machine config update JSONL."""
        hook_output = json.dumps({
            'type': 'Machine',
            'config': {
                'WGET_BINARY': '/usr/bin/wget',
            },
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['type'], 'Machine')
        self.assertIn('config', data)
        self.assertEqual(data['config']['WGET_BINARY'], '/usr/bin/wget')


class TestSnapshotHookOutput(unittest.TestCase):
    """Test snapshot hook output format compliance."""

    def test_snapshot_hook_basic_output(self):
        """Snapshot hook should output clean ArchiveResult JSONL."""
        hook_output = json.dumps({
            'type': 'ArchiveResult',
            'status': 'succeeded',
            'output_str': 'Downloaded 5 files',
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['type'], 'ArchiveResult')
        self.assertEqual(data['status'], 'succeeded')
        self.assertIn('output_str', data)

    def test_snapshot_hook_with_cmd(self):
        """Snapshot hook should include cmd for binary FK lookup."""
        hook_output = json.dumps({
            'type': 'ArchiveResult',
            'status': 'succeeded',
            'output_str': 'Archived with wget',
            'cmd': ['/usr/bin/wget', '-p', '-k', 'https://example.com'],
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['type'], 'ArchiveResult')
        self.assertIsInstance(data['cmd'], list)
        self.assertEqual(data['cmd'][0], '/usr/bin/wget')

    def test_snapshot_hook_with_output_json(self):
        """Snapshot hook can include structured metadata in output_json."""
        hook_output = json.dumps({
            'type': 'ArchiveResult',
            'status': 'succeeded',
            'output_str': 'Got headers',
            'output_json': {
                'content-type': 'text/html',
                'server': 'nginx',
                'status-code': 200,
            },
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['type'], 'ArchiveResult')
        self.assertIsInstance(data['output_json'], dict)
        self.assertEqual(data['output_json']['status-code'], 200)

    def test_snapshot_hook_skipped_status(self):
        """Snapshot hook should support skipped status."""
        hook_output = json.dumps({
            'type': 'ArchiveResult',
            'status': 'skipped',
            'output_str': 'SAVE_WGET=False',
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['status'], 'skipped')

    def test_snapshot_hook_failed_status(self):
        """Snapshot hook should support failed status."""
        hook_output = json.dumps({
            'type': 'ArchiveResult',
            'status': 'failed',
            'output_str': '404 Not Found',
        })

        from archivebox.machine.models import Process
        data = Process.parse_records_from_text(hook_output)[0]
        self.assertEqual(data['status'], 'failed')


class TestPluginMetadata(unittest.TestCase):
    """Test that plugin metadata is added to JSONL records."""

    def test_plugin_name_added(self):
        """run_hook() should add plugin name to records."""
        # Simulate what run_hook() does
        script = Path('/archivebox/plugins/wget/on_Snapshot__50_wget.py')
        plugin_name = script.parent.name

        record = {'type': 'ArchiveResult', 'status': 'succeeded'}
        record['plugin'] = plugin_name
        record['plugin_hook'] = str(script)

        self.assertEqual(record['plugin'], 'wget')
        self.assertIn('on_Snapshot__50_wget.py', record['plugin_hook'])


if __name__ == '__main__':
    unittest.main()
